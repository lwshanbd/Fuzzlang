"""Integration tests for FuzzlangClangVerifier against the real patched clang.

Skipped if the Fuzzlang-modified clang + diagtool are not available. To enable,
set FUZZLANG_CLANG_BIN and FUZZLANG_DIAGTOOL_BIN in the environment (or rely on
default /lus/eagle/projects/diomp/baodi/softwares/fuzzlang-clang/bin paths on
Polaris).

These tests validate:
  - the patched clang emits `DiagID: N` on stderr as expected,
  - FuzzlangClangVerifier parses it correctly,
  - diagtool reverse-lookup resolves to an err_* name.
"""
from __future__ import annotations

import os
import shutil

import pytest

from foundation.verifier.base import PLACEHOLDER
from foundation.verifier.fuzzlang import FuzzlangClangVerifier


DEFAULT_CLANG = "/lus/eagle/projects/diomp/baodi/softwares/fuzzlang-clang/bin/clang"
DEFAULT_DIAGTOOL = "/lus/eagle/projects/diomp/baodi/softwares/fuzzlang-clang/bin/diagtool"

CLANG_BIN = os.environ.get("FUZZLANG_CLANG_BIN", DEFAULT_CLANG)
DIAGTOOL_BIN = os.environ.get("FUZZLANG_DIAGTOOL_BIN", DEFAULT_DIAGTOOL)

_SKIP_REASON = (
    f"FuzzlangClangVerifier integration requires patched clang + diagtool. "
    f"Set FUZZLANG_CLANG_BIN + FUZZLANG_DIAGTOOL_BIN or place them at "
    f"{DEFAULT_CLANG} / {DEFAULT_DIAGTOOL}."
)


pytestmark = pytest.mark.skipif(
    not (os.path.isfile(CLANG_BIN) and os.access(CLANG_BIN, os.X_OK)
         and os.path.isfile(DIAGTOOL_BIN) and os.access(DIAGTOOL_BIN, os.X_OK)),
    reason=_SKIP_REASON,
)


@pytest.fixture
def verifier():
    return FuzzlangClangVerifier(CLANG_BIN, DIAGTOOL_BIN, timeout_s=15.0)


def test_patched_clang_emits_diag_id_and_we_parse_it(verifier):
    """Missing-semicolon source must yield a DiagInfo with integer diag_id + err_ name."""
    src = "int main() { int x = 1 }\n"
    cmd = ["__CLANG__", "-c", PLACEHOLDER, "-o", "/tmp/fuzzlang_itest.o"]
    result = verifier.verify(src, cmd, logical_path="/virt/missing_semi.c")
    try:
        assert not result.ok, "expected compile failure"
        assert result.diag is not None, "primary diagnostic must parse"
        assert result.diag.diag_id is not None
        assert result.diag.diag_id > 0
        # Name resolved via stock diagtool find-diagnostic-id reverse path.
        assert result.diag.diag_name is not None
        assert result.diag.diag_name.startswith("err_")
        assert "semi" in result.diag.diag_name or "expected" in result.diag.diag_name
        # File set to logical_path, not the tempfile.
        assert result.diag.file == "/virt/missing_semi.c"
        # Raw stderr must include the DiagID line the patch emits.
        assert "DiagID:" in result.raw_stderr
    finally:
        try:
            os.unlink("/tmp/fuzzlang_itest.o")
        except OSError:
            pass


def test_well_formed_source_verifies_ok(verifier):
    src = "int main() { return 0; }\n"
    cmd = ["__CLANG__", "-c", PLACEHOLDER, "-o", "/tmp/fuzzlang_itest_ok.o"]
    result = verifier.verify(src, cmd, logical_path="/virt/ok.c")
    try:
        assert result.ok
        assert result.diag is None
    finally:
        try:
            os.unlink("/tmp/fuzzlang_itest_ok.o")
        except OSError:
            pass


def test_span_hash_stable_across_repeated_verifies_of_same_source(verifier):
    """The whole point of logical_path: repeated verifies of the same logical
    source must produce the same DiagInfo.span_hash, so dead-end detection works."""
    src = "int main() { int x = 1 }\n"
    cmd = ["__CLANG__", "-c", PLACEHOLDER, "-o", "/tmp/fuzzlang_itest_hash.o"]
    r1 = verifier.verify(src, cmd, logical_path="/virt/same.c")
    r2 = verifier.verify(src, cmd, logical_path="/virt/same.c")
    try:
        assert r1.diag is not None and r2.diag is not None
        assert r1.diag.span_hash() == r2.diag.span_hash()
    finally:
        for f in ("/tmp/fuzzlang_itest_hash.o",):
            try:
                os.unlink(f)
            except OSError:
                pass


def test_diag_info_includes_position(verifier):
    src = "int main() {\n    int x = 1\n    return 0;\n}\n"  # missing ; on line 2
    cmd = ["__CLANG__", "-c", PLACEHOLDER, "-o", "/tmp/fuzzlang_itest_pos.o"]
    result = verifier.verify(src, cmd, logical_path="/virt/pos.c")
    try:
        assert not result.ok and result.diag is not None
        assert result.diag.line == 2
        assert result.diag.col > 0
        assert "int x = 1" in result.diag.span_snippet
    finally:
        try:
            os.unlink("/tmp/fuzzlang_itest_pos.o")
        except OSError:
            pass
