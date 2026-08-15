from __future__ import annotations

import json
from pathlib import Path

from foundation.types import DiagInfo, VerifierResult
from foundation.verifier.mock import MockVerifier, ok_result
from gen.realcorpus.corpus import (
    Fragment, build_fragment_index, is_test_path, is_vendored_path, sanitize_cmd,
)


def test_sanitize_cmd_drops_werror_only():
    cmd = ["__CLANG__", "-Werror", "-Werror=return-type", "-Wall", "-std=c++17", "__SRC__"]
    out = sanitize_cmd(cmd)
    assert "-Werror" not in out and "-Werror=return-type" not in out
    assert "-Wall" in out and "-std=c++17" in out


def _write_tu(tmp_path: Path, name: str, body: str) -> str:
    p = tmp_path / name
    p.write_text(body)
    return str(p)


def test_build_fragment_index_keeps_only_clean_tus(tmp_path: Path):
    good = _write_tu(tmp_path, "good.cpp", "int add(int a,int b){ return a+b; }\n")
    bad = _write_tu(tmp_path, "bad.cpp", "int oops(int a){ return a\n}\n")
    ccdb = tmp_path / "compile_commands.json"
    ccdb.write_text(json.dumps([
        {"directory": str(tmp_path), "file": good, "command": f"g++ -c {good}"},
        {"directory": str(tmp_path), "file": bad, "command": f"g++ -c {bad}"},
    ]))
    from foundation.compile_db import load_compile_db
    db = load_compile_db(ccdb)

    def policy(src, cmd, logical_path):
        # "good" body compiles; "bad" (missing ;) errors.
        if "return a\n" in src:
            return VerifierResult(ok=False, diag=DiagInfo(
                diag_id=1, diag_name="err_expected_semi", diag_msg="expected ';'",
                file=logical_path, line=1, col=1, start_byte=0, end_byte=1,
                span_snippet="x"), raw_stderr="error: expected ';'")
        return ok_result()

    frags = build_fragment_index(db, MockVerifier(policy),
                                 n_files=10, seed=0, max_regions_per_file=4)
    paths = {f.rel_path for f in frags}
    assert any("good.cpp" in p for p in paths)
    assert not any("bad.cpp" in p for p in paths)
    # a fragment carries its region text and a placeholdered compile cmd
    f = next(iter(frags))
    assert f.compile_cmd[0] == "__CLANG__" and f.compile_cmd[-1] == "__SRC__"
    assert f.region_text in f.tu_src


def test_is_test_path_flags_test_and_example_dirs():
    from gen.realcorpus.corpus import is_test_path
    assert is_test_path("/x/llvm/unittests/ADT/FooTest.cpp")
    assert is_test_path("/x/clang/examples/Bar/Bar.cpp")
    assert is_test_path("/x/third-party/unittest/googletest/src/gtest-all.cc")
    assert is_test_path("/x/clang/tools/c-index-test/c-index-test.c")
    assert is_test_path("/x/llvm/tools/llvm-c-test/main.c")
    assert is_test_path("/x/llvm/tools/bugpoint-passes/TestPasses.cpp")
    assert is_test_path("/x/llvm/tools/llvm-cov/TestingSupport.cpp")
    assert is_test_path(
        "/x/clang/lib/StaticAnalyzer/Checkers/TaintTesterChecker.cpp"
    )
    assert not is_test_path("/x/llvm/lib/Support/APInt.cpp")
    assert not is_test_path("/x/clang/lib/Sema/SemaDecl.cpp")


def test_build_fragment_index_excludes_test_files(tmp_path):
    import json
    from foundation.compile_db import load_compile_db
    from foundation.verifier.mock import MockVerifier, ok_result
    real = _write_tu(tmp_path, "APInt.cpp", "int add(int a,int b){ return a+b; }\n")
    testdir = tmp_path / "unittests"
    testdir.mkdir()
    tf = testdir / "FooTest.cpp"
    tf.write_text("int t(){ return 1; }\n")
    ccdb = tmp_path / "compile_commands.json"
    ccdb.write_text(json.dumps([
        {"directory": str(tmp_path), "file": real, "command": f"g++ -c {real}"},
        {"directory": str(tmp_path), "file": str(tf), "command": f"g++ -c {tf}"},
    ]))
    db = load_compile_db(ccdb)
    frags = build_fragment_index(db, MockVerifier(lambda s, c, l: ok_result()),
                                 n_files=10, seed=0)
    paths = {f.rel_path for f in frags}
    assert any("APInt.cpp" in p for p in paths)
    assert not any("FooTest.cpp" in p for p in paths)


def test_vendored_third_party_source_is_not_a_project_source():
    """A build tree that fetches a dependency makes that dependency's code look
    like the project's own.  duckdb and protobuf both vendor Abseil under
    `build/_deps/absl-src/`, so Abseil source entered training labelled as
    duckdb/protobuf -- while Abseil was a held-out evaluation project.
    """
    assert is_vendored_path("build/_deps/absl-src/absl/strings/ascii.cc")
    assert is_vendored_path("build/_deps/googletest-src/src/gtest.cc")
    assert is_vendored_path("third_party/re2/re2.cc")
    assert is_vendored_path("vendor/zlib/deflate.c")
    assert is_vendored_path("contrib/lib.c")
    assert is_vendored_path("deps/foo/bar.c")

    # A project's own source must not be swept up.
    assert not is_vendored_path("absl/strings/ascii.cc")
    assert not is_vendored_path("src/duckdb/parser/parser.cpp")
    assert not is_vendored_path("llvm/lib/Support/Path.cpp")
    assert not is_vendored_path("libavcodec/h264dec.c")


def test_generated_build_output_is_not_a_project_source():
    """CMake unity-build stubs are generated `#include` lists, not real code."""
    assert is_vendored_path(
        "build/extension/core_functions/ub_duckdb_core_functions_math.cpp"
    )
    assert is_vendored_path("build/CMakeFiles/foo.dir/x.cc")
    assert not is_vendored_path("src/ub_handwritten.cpp")


def test_the_test_filter_is_unchanged_by_the_vendored_filter():
    assert is_test_path("clang/test/Sema/x.cpp")
    assert not is_test_path("absl/strings/ascii.cc")
