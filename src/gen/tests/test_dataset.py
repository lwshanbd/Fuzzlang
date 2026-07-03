"""Tests for dataset assembly: structural dedup + provenance-isolated splits."""
from __future__ import annotations

from foundation.record import Origin, Provenance, Record, Split
from foundation.types import DiagInfo
from gen.dataset import dedup_records, split_records


def _rec(rid, *, diag="err_x", src="int main(){\n  int x = 1\n  return x;\n}\n",
         line=2, source="guided:err_x"):
    d = DiagInfo(diag_id=1, diag_name=diag, diag_msg="m", file="t.cpp",
                 line=line, col=1, start_byte=0, end_byte=1, span_snippet="x")
    return Record(record_id=rid, erroneous_src=src, corrected_src="int main(){}\n",
                  diagnostics=[d], provenance=Provenance(Origin.GUIDED, source),
                  split=Split.TRAIN)


# ---- dedup ------------------------------------------------------------------

def test_dedup_drops_structurally_identical_records():
    a = _rec("1")
    b = _rec("2")  # same diag + same code window
    assert len(dedup_records([a, b])) == 1


def test_dedup_ignores_whitespace_differences():
    a = _rec("1", src="int main(){\n  int x = 1\n  return x;\n}\n")
    b = _rec("2", src="int main(){\n      int  x  =  1\n  return x;\n}\n")  # same tokens
    assert len(dedup_records([a, b])) == 1


def test_dedup_keeps_genuinely_different_programs():
    a = _rec("1", src="int main(){\n  int x = 1\n  return x;\n}\n")
    b = _rec("2", src="struct S{\n  int a\n};\nint main(){}\n")
    assert len(dedup_records([a, b])) == 2


def test_dedup_keeps_same_code_under_different_diagnostics():
    a = _rec("1", diag="err_x")
    b = _rec("2", diag="err_y")
    assert len(dedup_records([a, b])) == 2


def test_dedup_is_order_stable():
    a, b, c = _rec("1"), _rec("2", diag="err_y"), _rec("3")
    kept = dedup_records([a, b, c])
    assert [r.record_id for r in kept] == ["1", "2"]   # first of each key


# ---- splits -----------------------------------------------------------------

def _many(n):
    return [_rec(str(i), diag=f"err_{i}", source=f"guided:err_{i}") for i in range(n)]


def test_split_assigns_every_record_and_sets_split_field():
    parts = split_records(_many(200), salt="s")
    total = sum(len(v) for v in parts.values())
    assert total == 200
    for split, recs in parts.items():
        assert all(r.split is split for r in recs)


def test_split_is_provenance_isolated():
    # Several records sharing one provenance source must all land together.
    recs = [_rec(str(i), source="guided:shared") for i in range(20)]
    recs += [_rec("z", source="guided:other")]
    parts = split_records(recs, salt="s")
    src_to_splits = {}
    for split, rs in parts.items():
        for r in rs:
            src_to_splits.setdefault(r.provenance.source, set()).add(split)
    assert all(len(s) == 1 for s in src_to_splits.values())   # no source straddles


def test_split_is_deterministic():
    recs = _many(100)
    a = split_records(recs, salt="s")
    b = split_records(recs, salt="s")
    assert {k: [r.record_id for r in v] for k, v in a.items()} == \
           {k: [r.record_id for r in v] for k, v in b.items()}


def test_split_fractions_are_approximately_right():
    parts = split_records(_many(1000), salt="s", dev_fraction=0.1, eval_fraction=0.1)
    assert 0.7 <= len(parts[Split.TRAIN]) / 1000 <= 0.9
    assert len(parts[Split.DEV]) > 30 and len(parts[Split.EVAL]) > 30
