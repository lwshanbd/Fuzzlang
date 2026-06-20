"""Tests for the human-readable coverage report formatter."""
from coverage.report import format_report
from coverage.tracker import build_report
from foundation.diagnostics.catalog import Catalog, DiagEntry
from foundation.record import Origin, Provenance, Record, Split
from foundation.types import DiagInfo


def _catalog():
    e = lambda n, c: DiagEntry(name=n, severity="Error", message="", component=c)
    return Catalog([e("err_a", "Sema"), e("err_b", "Sema"),
                    e("err_c", "Parse"), e("err_d", "Parse")])


def _rec(name, rid):
    d = DiagInfo(diag_id=None, diag_name=name, diag_msg="m", file="t.cpp",
                 line=1, col=1, start_byte=0, end_byte=1, span_snippet="x")
    return Record(record_id=rid, erroneous_src="bad", corrected_src="good",
                  diagnostics=[d], provenance=Provenance(Origin.MUTATE, "s"),
                  split=Split.TRAIN)


def test_format_contains_headline_numbers():
    r = build_report([_rec("err_a", "1"), _rec("err_a", "2"), _rec("err_c", "3")],
                     _catalog(), multiplicity_target=2)
    s = format_report(r)
    assert "2/4" in s          # covered / total
    assert "50" in s           # 50% coverage
    assert "Sema" in s         # per-component breakdown
    assert "gap" in s.lower()  # gap summary
