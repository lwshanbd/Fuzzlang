"""FuzzlangClangVerifier must tolerate non-UTF-8 bytes on clang's stderr.

Some frontend configs (certain targets / inputs) make clang emit non-UTF-8
bytes in a diagnostic. Strict decoding crashed the whole mining sweep; the
verifier must decode robustly and still parse the DiagID.
"""
from __future__ import annotations

import os

from foundation.verifier.base import PLACEHOLDER
from foundation.verifier.fuzzlang import FuzzlangClangVerifier, _guess_suffix


def test_guess_suffix_uses_stable_logical_path_when_command_has_no_language():
    command = ["__CLANG__", "-I/project", "-fsyntax-only", "__SRC__"]

    assert _guess_suffix(command, "absl/base/log_severity.cc") == ".cpp"
    assert _guess_suffix(command, "src/runtime.c") == ".c"
    assert _guess_suffix(command, "runtime/NSObject.m") == ".m"
    assert _guess_suffix(command, "runtime/Selector.mm") == ".mm"


def test_guess_suffix_respects_explicit_language_over_logical_path():
    assert _guess_suffix(
        ["__CLANG__", "-x", "c", "__SRC__"], "src/misnamed.cc"
    ) == ".c"


def test_verifier_can_select_distinct_c_and_cxx_drivers() -> None:
    verifier = FuzzlangClangVerifier(
        "clang++", "diagtool", clang_c_bin="clang"
    )
    command = ["__CLANG__", "-fsyntax-only", "__SRC__"]

    assert verifier._compiler_for(command, "src/runtime.c") == "clang"
    assert verifier._compiler_for(command, "src/runtime.cc") == "clang++"
    assert verifier._compiler_for(command, "src/runtime.m") == "clang"
    assert verifier._compiler_for(command, "src/runtime.mm") == "clang++"


def test_verify_tolerates_non_utf8_stderr(tmp_path):
    fake = tmp_path / "fakeclang"
    # Emits an error line containing a raw 0xb2 byte, then a DiagID, exits 1.
    fake.write_text(
        '#!/bin/bash\n'
        r'printf "f.c:1:1: error: bad \xb2 byte\nDiagID: 42\n" >&2' + '\n'
        'exit 1\n'
    )
    os.chmod(fake, 0o755)

    v = FuzzlangClangVerifier(str(fake), "/bin/true")
    result = v.verify("int x;", ["__CLANG__", PLACEHOLDER], logical_path="f.c")

    assert not result.ok
    assert result.diag is not None
    assert result.diag.diag_id == 42        # parsed despite the bad byte
    assert "DiagID:" in result.raw_stderr
