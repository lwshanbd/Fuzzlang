from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from foundation.compile_db import load_compile_db
from foundation.record import Origin, Provenance, Record, Split
from foundation.types import DiagInfo, VerifierResult
from foundation.verifier.mock import MockVerifier, ok_result
from gen.realcorpus.clean_source_pool import (
    CleanSourceTU,
    build_clean_source_pool,
    build_clean_source_pool_from_records,
    load_clean_sources_jsonl,
)
from gen.realcorpus import run_clean_source_pool as cli
from gen.realcorpus import run_clean_source_pool_from_records as record_cli


def _source(*, path: str = "llvm/lib/IR/Thing.cpp", text: str = "int f() { return 0; }\n"):
    return CleanSourceTU(
        source_id=f"llvm:{path}",
        project="llvm",
        source_path=path,
        language="c++",
        corrected_src=text,
        compile_cmd=("__CLANG__", "-std=c++20", "-fsyntax-only", "__SRC__"),
        source_sha256=hashlib.sha256(text.encode()).hexdigest(),
        baseline_compiler="llvmorg-22.1.8",
    )


def _diag(path: str) -> DiagInfo:
    return DiagInfo(
        diag_id=1,
        diag_name="err_expected_semi",
        diag_msg="expected ';'",
        file=path,
        line=1,
        col=1,
        start_byte=0,
        end_byte=1,
        span_snippet="x",
    )


def test_clean_source_tu_round_trips_with_content_hash(tmp_path):
    source = _source()
    path = tmp_path / "sources.jsonl"
    path.write_text(json.dumps(source.to_dict(), sort_keys=True) + "\n")

    loaded = load_clean_sources_jsonl(path)

    assert loaded == [source]
    assert loaded[0].to_dict()["schema"] == "fuzzlang.clean_source_tu"
    assert loaded[0].to_dict()["source_sha256"] == hashlib.sha256(
        source.corrected_src.encode()
    ).hexdigest()


def test_clean_source_tu_rejects_test_paths_bad_hash_and_invalid_command():
    with pytest.raises(ValueError, match="test"):
        _source(path="clang/test/Sema/Bad.cpp")
    with pytest.raises(ValueError, match="source_sha256"):
        CleanSourceTU(
            source_id="llvm:llvm/lib/IR/Bad.cpp",
            project="llvm",
            source_path="llvm/lib/IR/Bad.cpp",
            language="c++",
            corrected_src="int f() { return 0; }\n",
            compile_cmd=("__CLANG__", "__SRC__"),
            source_sha256="0" * 64,
            baseline_compiler="llvmorg-22.1.8",
        )
    with pytest.raises(ValueError, match="compile_cmd"):
        CleanSourceTU(
            source_id="llvm:llvm/lib/IR/Bad.cpp",
            project="llvm",
            source_path="llvm/lib/IR/Bad.cpp",
            language="c++",
            corrected_src="int f() { return 0; }\n",
            compile_cmd=("clang++", "-fsyntax-only"),
            source_sha256=hashlib.sha256(
                b"int f() { return 0; }\n"
            ).hexdigest(),
            baseline_compiler="llvmorg-22.1.8",
        )


def test_build_clean_source_pool_keeps_only_unseen_non_test_clean_tus(tmp_path):
    root = tmp_path / "llvm"
    good = root / "llvm/lib/IR/Good.cpp"
    bad = root / "llvm/lib/IR/Bad.cpp"
    excluded = root / "clang/lib/Sema/Excluded.cpp"
    test = root / "clang/test/Sema/Test.cpp"
    for path, contents in (
        (good, "int good() { return 0; }\n"),
        (bad, "int bad() { return missing; }\n"),
        (excluded, "int excluded() { return 0; }\n"),
        (test, "int test() { return 0; }\n"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)
    ccdb = tmp_path / "compile_commands.json"
    ccdb.write_text(json.dumps([
        {"directory": str(tmp_path), "file": str(path),
         "command": f"clang++ -c {path}"}
        for path in (good, bad, excluded, test)
    ]))
    db = load_compile_db(ccdb)
    verifier = MockVerifier(lambda src, _cmd, path: (
        VerifierResult(False, _diag(path), "error") if "missing" in src else ok_result()
    ))

    result = build_clean_source_pool(
        db,
        verifier,
        project="llvm",
        source_root=str(root),
        excluded_source_ids={"llvm:clang/lib/Sema/Excluded.cpp"},
        workers=2,
    )

    assert [item.source_id for item in result.sources] == ["llvm:llvm/lib/IR/Good.cpp"]
    assert result.sources[0].compile_cmd[0] == "__CLANG__"
    assert result.sources[0].compile_cmd[-1] == "__SRC__"
    assert result.counts == {
        "compile_db_entries": 4,
        "source_candidates": 3,
        "excluded_known_sources": 1,
        "test_sources": 1,
        "attempted_clean_gates": 2,
        "accepted_clean_sources": 1,
    }
    assert [(item.status, item.source_id) for item in result.rejections] == [
        ("corrected_not_clean", "llvm:llvm/lib/IR/Bad.cpp"),
    ]


def test_build_clean_source_pool_from_records_revalidates_real_paired_parents():
    def record(source: str, text: str, *, path: str, command: list[str]):
        return Record(
            record_id=f"record-{source}",
            erroneous_src=text.replace("0", "missing"),
            corrected_src=text,
            diagnostics=(_diag(path),),
            provenance=Provenance(
                Origin.LLM,
                source,
                {
                    "source_path": path,
                    "compile_cmd": command,
                },
            ),
            split=Split.TRAIN,
            language="c++",
        )

    good = record(
        "abseil:absl/strings/good.cc", "int good() { return 0; }\n",
        path="absl/strings/good.cc",
        command=["__CLANG__", "-fsyntax-only", "__SRC__"],
    )
    duplicate = record(
        "abseil:absl/strings/good.cc", "int good() { return 0; }\n",
        path="absl/strings/good.cc",
        command=["__CLANG__", "-fsyntax-only", "__SRC__"],
    )
    test = record(
        "abseil:absl/strings/test/bad.cc", "int test() { return 0; }\n",
        path="absl/strings/test/bad.cc",
        command=["__CLANG__", "-fsyntax-only", "__SRC__"],
    )
    malformed = record(
        "abseil:absl/strings/invalid.cc", "int invalid() { return 0; }\n",
        path="absl/strings/invalid.cc",
        command=["clang++", "-fsyntax-only"],
    )
    verifier = MockVerifier(lambda src, _cmd, path: (
        VerifierResult(False, _diag(path), "error") if "invalid" in src else ok_result()
    ))

    result = build_clean_source_pool_from_records(
        [good, duplicate, test, malformed], verifier, project="abseil",
    )

    assert [item.source_id for item in result.sources] == [
        "abseil:absl/strings/good.cc",
    ]
    assert result.sources[0].compile_cmd == (
        "__CLANG__", "-fsyntax-only", "__SRC__",
    )
    assert result.counts == {
        "record_candidates": 4,
        "matching_project_records": 4,
        "unique_source_candidates": 1,
        "duplicate_parent_records": 1,
        "test_sources": 1,
        "invalid_record_provenance": 1,
        "excluded_known_sources": 0,
        "attempted_clean_gates": 1,
        "accepted_clean_sources": 1,
    }


def test_clean_source_pool_cli_archives_outputs_and_exclusion_provenance(
    tmp_path, monkeypatch,
):
    root = tmp_path / "llvm"
    source = root / "llvm/lib/IR/Good.cpp"
    source.parent.mkdir(parents=True)
    source.write_text("int good() { return 0; }\n")
    ccdb = tmp_path / "compile_commands.json"
    ccdb.write_text(json.dumps([{
        "directory": str(tmp_path), "file": str(source),
        "command": f"clang++ -c {source}",
    }]))
    out = tmp_path / "sources.jsonl"
    rejected = tmp_path / "rejected.jsonl"
    manifest = tmp_path / "manifest.json"

    class Verifier:
        def __init__(self, *_args, **_kwargs):
            pass

        def verify(self, *_args, **_kwargs):
            return ok_result()

    monkeypatch.setattr(cli, "FuzzlangClangVerifier", Verifier)
    assert cli.main([
        "--compile-db", str(ccdb),
        "--clang-bin", "/mock/clang++",
        "--clang-c-bin", "/mock/clang",
        "--diagtool-bin", "/mock/diagtool",
        "--project", "llvm",
        "--source-root", str(root),
        "--out", str(out),
        "--rejections-out", str(rejected),
        "--manifest-out", str(manifest),
    ]) == 0

    source_row = json.loads(out.read_text())
    payload = json.loads(manifest.read_text())
    assert source_row["source_id"] == "llvm:llvm/lib/IR/Good.cpp"
    assert payload["source_policy"]["test_and_test_support_excluded"] is True
    assert payload["counts"]["accepted_clean_sources"] == 1
    assert payload["outputs"]["sources"]["sha256"] == hashlib.sha256(
        out.read_bytes()
    ).hexdigest()


def test_clean_source_pool_from_records_cli_revalidates_parent(tmp_path, monkeypatch):
    source = Record(
        record_id="abseil-parent",
        erroneous_src="int source() { return missing; }\n",
        corrected_src="int source() { return 0; }\n",
        diagnostics=(_diag("absl/base/source.cc"),),
        provenance=Provenance(
            Origin.LLM,
            "abseil:absl/base/source.cc",
            {
                "source_path": "absl/base/source.cc",
                "compile_cmd": ["__CLANG__", "-fsyntax-only", "__SRC__"],
            },
        ),
        split=Split.TRAIN,
        language="c++",
    )
    records = tmp_path / "records.jsonl"
    records.write_text(json.dumps(source.to_dict()) + "\n")
    out = tmp_path / "sources.jsonl"
    rejected = tmp_path / "rejected.jsonl"
    manifest = tmp_path / "manifest.json"

    class Verifier:
        def __init__(self, *_args, **_kwargs):
            pass

        def verify(self, *_args, **_kwargs):
            return ok_result()

    monkeypatch.setattr(record_cli, "FuzzlangClangVerifier", Verifier)
    assert record_cli.main([
        "--records", str(records),
        "--clang-bin", "/mock/clang++",
        "--clang-c-bin", "/mock/clang",
        "--diagtool-bin", "/mock/diagtool",
        "--project", "abseil",
        "--out", str(out),
        "--rejections-out", str(rejected),
        "--manifest-out", str(manifest),
    ]) == 0

    row = json.loads(out.read_text())
    payload = json.loads(manifest.read_text())
    assert row["source_id"] == "abseil:absl/base/source.cc"
    assert payload["source_policy"]["record_derived_parents_revalidated"] is True
    assert payload["counts"]["accepted_clean_sources"] == 1
