from __future__ import annotations

import json
from pathlib import Path

from foundation.diagnostics.catalog import DiagEntry
from gen.realcorpus.targets import Target, build_targets, load_exemplars


def test_load_exemplars_maps_name_to_erroneous_src(tmp_path: Path):
    ds = tmp_path / "train.jsonl"
    ds.write_text(json.dumps({
        "record_id": "x", "erroneous_src": "int f(){return 0}",
        "corrected_src": "int f(){return 0;}",
        "diagnostics": [{"diag_id": 1, "diag_name": "err_expected_semi",
                         "diag_msg": "m", "file": "f", "line": 1, "col": 1,
                         "start_byte": 0, "end_byte": 1, "span_snippet": "x"}],
        "provenance": {"origin": "guided", "source": "s", "detail": {}},
        "split": "train", "language": "c"}) + "\n")
    ex = load_exemplars(ds)
    assert ex["err_expected_semi"] == "int f(){return 0}"


def test_build_targets_excludes_out_of_scope_and_orders_covered_first():
    entries = [
        DiagEntry(name="err_omp_bad", severity="Error", message="omp"),        # out of scope
        DiagEntry(name="err_uncovered", severity="Error", message="x"),        # in scope, no exemplar
        DiagEntry(name="err_covered", severity="Error", message="y"),          # in scope, has exemplar
    ]
    targets = build_targets(entries, out_of_scope={"err_omp_bad"},
                            exemplars={"err_covered": "buggy"})
    names = [t.name for t in targets]
    assert "err_omp_bad" not in names
    assert names.index("err_covered") < names.index("err_uncovered")  # covered first
    assert targets[0].exemplar == "buggy" and targets[0].covered is True


def test_build_targets_deprioritizes_pathological_families():
    entries = [
        DiagEntry(name="err_asm_bad", severity="Error", message="asm"),
        DiagEntry(name="err_typecheck_bad", severity="Error", message="type"),
    ]
    targets = build_targets(entries, out_of_scope=set(), exemplars={})
    names = [t.name for t in targets]
    assert names.index("err_typecheck_bad") < names.index("err_asm_bad")
