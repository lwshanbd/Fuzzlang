from __future__ import annotations

import json
from pathlib import Path

from foundation.diagnostics.catalog import DiagEntry
from gen.realcorpus.targets import (Target, build_targets, load_exemplars,
                                    load_observed_names,
                                    load_diagnostic_languages)


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
    assert "Correct code" in ex["err_expected_semi"]
    assert "int f(){return 0;}" in ex["err_expected_semi"]
    assert "Broken code" in ex["err_expected_semi"]
    assert "int f(){return 0}" in ex["err_expected_semi"]


def test_load_observed_names_accepts_record_and_run_sweep_rows(tmp_path: Path):
    records = tmp_path / "records.jsonl"
    records.write_text(json.dumps({
        "diagnostics": [{"diag_name": "err_from_record"}],
    }) + "\n")
    sweep = tmp_path / "sweep.jsonl"
    sweep.write_text(json.dumps({"diag_name": "err_from_sweep"}) + "\n")
    assert load_observed_names([records, sweep]) == {
        "err_from_record", "err_from_sweep",
    }


def test_load_diagnostic_languages_groups_exemplars(tmp_path: Path):
    ds = tmp_path / "records.jsonl"
    ds.write_text("\n".join([
        json.dumps({"language": "c", "diagnostics": [{"diag_name": "err_both"}]}),
        json.dumps({"language": "c++", "diagnostics": [{"diag_name": "err_both"}]}),
        json.dumps({"language": "c", "diagnostics": [{"diag_name": "err_c"}]}),
    ]) + "\n")
    assert load_diagnostic_languages(ds) == {
        "err_both": {"c", "c++"}, "err_c": {"c"},
    }


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


def test_build_targets_real_gap_first_prefers_unseen_with_exemplar():
    entries = [
        DiagEntry(name="err_seen", severity="Error", message="call"),
        DiagEntry(name="err_unseen_no_example", severity="Error", message="call"),
        DiagEntry(name="err_unseen_with_example", severity="Error", message="call"),
    ]
    targets = build_targets(
        entries, out_of_scope=set(),
        exemplars={"err_seen": "a", "err_unseen_with_example": "b"},
        observed_names={"err_seen"}, order_mode="real-gap-first",
    )
    assert [t.name for t in targets] == [
        "err_unseen_with_example", "err_unseen_no_example", "err_seen",
    ]
    assert targets[0].observed_in_real is False
    assert targets[-1].observed_in_real is True


def test_build_targets_can_filter_to_explicit_target_names():
    entries = [
        DiagEntry(name="err_a", severity="Error", message="a"),
        DiagEntry(name="err_b", severity="Error", message="b"),
    ]
    targets = build_targets(entries, out_of_scope=set(), exemplars={},
                            include_names={"err_b"})
    assert [t.name for t in targets] == ["err_b"]


def test_build_targets_can_exclude_invocation_components():
    entries = [
        DiagEntry(name="err_code", severity="Error", message="x", component="Sema"),
        DiagEntry(name="err_driver", severity="Error", message="x", component="Driver"),
    ]
    targets = build_targets(entries, out_of_scope=set(), exemplars={},
                            exclude_components={"Driver"})
    assert [t.name for t in targets] == ["err_code"]
