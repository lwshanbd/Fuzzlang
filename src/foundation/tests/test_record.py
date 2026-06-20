"""Tests for the dataset record schema.

A FuzzLang record pairs an erroneous program with its corrected origin plus
the diagnostic it triggers. The defining invariant: a *core* record must carry
a corrected version (errors are introduced into correct code). Broken-only
material is allowed only in the AUXILIARY split.
"""
import json

import pytest

from foundation.record import Origin, Provenance, Record, Split
from foundation.types import DiagInfo


def _diag(name="err_expected_semi_declaration"):
    return DiagInfo(
        diag_id=1234,
        diag_name=name,
        diag_msg="expected ';' after declaration",
        file="t.cpp",
        line=3,
        col=10,
        start_byte=20,
        end_byte=21,
        span_snippet="x",
    )


def _prov(origin=Origin.MUTATE):
    return Provenance(origin=origin, source="llvm:clang/lib/Sema/Foo.cpp",
                      detail={"mutation": "remove_semicolon"})


def _core_record(**over):
    kw = dict(
        record_id="r1",
        erroneous_src="int x = 1\nint y = 2;\n",
        corrected_src="int x = 1;\nint y = 2;\n",
        diagnostics=[_diag()],
        provenance=_prov(),
        split=Split.TRAIN,
    )
    kw.update(over)
    return Record(**kw)


def test_core_record_roundtrips_through_json():
    rec = _core_record()
    restored = Record.from_dict(json.loads(json.dumps(rec.to_dict())))
    assert restored == rec


def test_core_record_requires_corrected_src():
    with pytest.raises(ValueError):
        _core_record(corrected_src=None)


def test_auxiliary_split_allows_missing_corrected_src():
    rec = _core_record(corrected_src=None, split=Split.AUXILIARY)
    assert rec.corrected_src is None
    assert not rec.is_core


def test_record_requires_at_least_one_diagnostic():
    with pytest.raises(ValueError):
        _core_record(diagnostics=[])


def test_empty_erroneous_src_rejected():
    with pytest.raises(ValueError):
        _core_record(erroneous_src="")


def test_primary_diagnostic_and_is_core():
    rec = _core_record(diagnostics=[_diag("err_a"), _diag("err_b")])
    assert rec.primary_diagnostic.diag_name == "err_a"
    assert rec.is_core
