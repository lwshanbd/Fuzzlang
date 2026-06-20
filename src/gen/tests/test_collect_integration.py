"""Integration test: real mutation -> real patched clang -> real Record.

Skipped unless the Fuzzlang-modified clang + diagtool are available. Enable by
setting FUZZLANG_CLANG_BIN and FUZZLANG_DIAGTOOL_BIN (same convention as
test_verifier_fuzzlang_integration.py).
"""
from __future__ import annotations

import os

import pytest

from foundation.record import Origin, Split
from foundation.verifier.fuzzlang import FuzzlangClangVerifier
from gen.collect import collect_records
from gen.mutate.delete_semicolon import DeleteSemicolon

DEFAULT_CLANG = "/lus/eagle/projects/diomp/baodi/softwares/fuzzlang-clang/bin/clang"
DEFAULT_DIAGTOOL = "/lus/eagle/projects/diomp/baodi/softwares/fuzzlang-clang/bin/diagtool"
CLANG_BIN = os.environ.get("FUZZLANG_CLANG_BIN", DEFAULT_CLANG)
DIAGTOOL_BIN = os.environ.get("FUZZLANG_DIAGTOOL_BIN", DEFAULT_DIAGTOOL)

pytestmark = pytest.mark.skipif(
    not (os.path.isfile(CLANG_BIN) and os.access(CLANG_BIN, os.X_OK)
         and os.path.isfile(DIAGTOOL_BIN) and os.access(DIAGTOOL_BIN, os.X_OK)),
    reason="needs patched clang+diagtool (set FUZZLANG_CLANG_BIN/FUZZLANG_DIAGTOOL_BIN)",
)


@pytest.fixture
def verifier():
    return FuzzlangClangVerifier(CLANG_BIN, DIAGTOOL_BIN, timeout_s=15.0)


def test_delete_semicolon_yields_record_with_real_diag(verifier):
    correct = "int main() {\n    int x = 1;\n    return 0;\n}\n"
    records = collect_records(correct, verifier, source="unit:integration",
                              language="c", mutations=[DeleteSemicolon()])
    assert records, "expected at least one verified mutant record"
    r = records[0]
    # Pairing + provenance.
    assert r.corrected_src == correct
    assert r.erroneous_src != correct
    assert r.provenance.origin is Origin.MUTATE
    assert r.split is Split.TRAIN
    # The diagnostic is real: an integer id resolved to an err_* name by the
    # patched clang + diagtool.
    d = r.primary_diagnostic
    assert d.diag_id is not None and d.diag_id > 0
    assert d.diag_name is not None and d.diag_name.startswith("err_")
    assert "semi" in d.diag_name or "expected" in d.diag_name
