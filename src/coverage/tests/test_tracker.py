"""Tests for the coverage tracker (the headline metric).

Coverage = how many of the catalog's error diagnostics (the denominator) the
dataset's records actually trigger, with multiplicity, plus the gap list of
uncovered / under-covered diagnostics that drives generation.
"""
from coverage.tracker import build_report
from foundation.diagnostics.catalog import Catalog, DiagEntry
from foundation.record import Origin, Provenance, Record, Split
from foundation.types import DiagInfo


def _catalog():
    e = lambda n, c: DiagEntry(name=n, severity="Error", message="", component=c)
    return Catalog([
        e("err_a", "Sema"), e("err_b", "Sema"),
        e("err_c", "Parse"), e("err_d", "Parse"),
        DiagEntry(name="warn_x", severity="Warning", message="", component="Sema"),
    ])


def _rec(name, rid):
    d = DiagInfo(diag_id=None, diag_name=name, diag_msg="m", file="t.cpp",
                 line=1, col=1, start_byte=0, end_byte=1, span_snippet="x")
    return Record(record_id=rid, erroneous_src="bad", corrected_src="good",
                  diagnostics=[d], provenance=Provenance(Origin.MUTATE, "s"),
                  split=Split.TRAIN)


def _records():
    return [_rec("err_a", "1"), _rec("err_a", "2"), _rec("err_a", "3"),
            _rec("err_c", "4"), _rec("err_unknown", "5")]


def test_counts_and_covered():
    r = build_report(_records(), _catalog(), multiplicity_target=2)
    assert r.total == 4                     # 4 error diagnostics (warn_x excluded)
    assert r.covered == 2                   # err_a, err_c
    assert r.counts == {"err_a": 3, "err_c": 1}
    assert r.coverage_fraction == 0.5


def test_multiplicity_target():
    r = build_report(_records(), _catalog(), multiplicity_target=2)
    assert r.covered_at_target == 1         # only err_a reaches 2 examples


def test_out_of_denominator_diagnostics_ignored():
    r = build_report(_records(), _catalog(), multiplicity_target=2)
    assert "err_unknown" not in r.counts    # not an error in the catalog


def test_gap_list_uncovered_and_undercovered():
    r = build_report(_records(), _catalog(), multiplicity_target=2)
    gaps = r.gap_list()
    # err_b, err_d uncovered (0); err_c undercovered (1<2); err_a meets target -> excluded
    assert [name for name, _ in gaps] == ["err_b", "err_d", "err_c"]
    assert dict(gaps) == {"err_b": 0, "err_d": 0, "err_c": 1}


def test_by_component():
    r = build_report(_records(), _catalog(), multiplicity_target=2)
    bc = r.by_component()
    assert bc["Sema"] == (1, 2)             # err_a covered of {err_a, err_b}
    assert bc["Parse"] == (1, 2)            # err_c covered of {err_c, err_d}


def test_none_diag_name_does_not_crash():
    d = DiagInfo(diag_id=None, diag_name=None, diag_msg="m", file="t.cpp",
                 line=1, col=1, start_byte=0, end_byte=1, span_snippet="x")
    rec = Record(record_id="z", erroneous_src="bad", corrected_src="good",
                 diagnostics=[d], provenance=Provenance(Origin.MUTATE, "s"),
                 split=Split.TRAIN)
    r = build_report([rec], _catalog(), multiplicity_target=2)
    assert r.covered == 0


def _catalog_with_invocation():
    e = lambda n, c: DiagEntry(name=n, severity="Error", message="", component=c)
    return Catalog([
        e("err_a", "Sema"), e("err_c", "Parse"),
        e("err_drv_x", "Driver"), e("err_fe_y", "Frontend"),
    ])


def test_exclude_components_filters_denominator():
    from coverage.tracker import build_report as br
    recs = [_rec("err_a", "1"), _rec("err_drv_x", "2")]
    r = br(recs, _catalog_with_invocation(),
           multiplicity_target=1, exclude_components=("Driver", "Frontend"))
    assert r.total == 2                       # only Sema + Parse remain
    assert "err_drv_x" not in r.counts        # excluded diagnostic not counted
    assert r.counts == {"err_a": 1}
    assert set(r.by_component()) == {"Sema", "Parse"}
