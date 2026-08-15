from __future__ import annotations

import json

import pytest

from repair.quality_report import (
    build_quality_report,
    edit_size_profile,
    injector_operations,
    record_operations,
    quality_rows,
    operation_rows,
)


def _audit(directory, config, cohort, rows):
    (directory / f"{config}--{cohort}.json").write_text(json.dumps({"n": len(rows)}))
    (directory / f"{config}--{cohort}.instances.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows)
    )


def _row(record_id, *, compile_ok=True, degenerate=False, edit_size=40):
    return {
        "record_id": record_id,
        "compile_ok": compile_ok,
        "ground_truth_ok": True,
        "exact_match": False,
        "quality": {
            "degenerate": degenerate,
            "pure_line_deletion": degenerate,
            "large_deletion": False,
            "excessive_edit": False,
            "empty_repair": False,
            "predicted_edit_size": edit_size,
            "gold_edit_size": 40,
        },
    }


def test_injector_operations_read_the_edit_operation_from_the_library(tmp_path):
    library = tmp_path / "library.jsonl"
    library.write_text(
        json.dumps({"injector_id": "a", "edit": {"operation": "replace"}}) + "\n"
        + json.dumps({"injector_id": "b", "edit": {"operation": "insert"}}) + "\n"
    )
    assert injector_operations(library) == {"a": "replace", "b": "insert"}


def test_record_operations_join_through_the_injector_id():
    records = [
        {"record_id": "r0", "provenance": {"detail": {"injector_id": "a"}}},
        {"record_id": "r1", "provenance": {"detail": {"injector_id": "missing"}}},
        {"record_id": "r2", "provenance": {"detail": {}}},
    ]
    assert record_operations(records, {"a": "replace"}) == {
        "r0": "replace", "r1": "unknown", "r2": "unknown",
    }


def test_report_averages_degeneracy_over_seeds_within_an_arm(tmp_path):
    # Two seeds of one arm: 3 of 4 fixes clean, then 2 of 4.  The arm's
    # degenerate share must average the seeds rather than pool the instances,
    # so that a seed with more fixes does not dominate the rate.
    _audit(tmp_path, "fuzzlang-seed42", "heldout_project",
           [_row("r0"), _row("r1"), _row("r2"), _row("r3", degenerate=True)])
    _audit(tmp_path, "fuzzlang-seed7", "heldout_project",
           [_row("r0"), _row("r1"), _row("r2", degenerate=True),
            _row("r3", degenerate=True)])

    report = build_quality_report(tmp_path, operation_by_record={})
    arm = report["cohorts"]["heldout_project"]["arms"]["fuzzlang"]

    assert arm["seeds"] == ["42", "7"]
    assert arm["verified_fixes_mean"] == 4.0
    assert arm["degenerate_mean"] == 1.5
    assert arm["degenerate_share"] == pytest.approx(0.375)
    # The share the paper quotes: fixes that survive the audit.
    assert arm["nondegenerate_share"] == pytest.approx(0.625)


def test_report_splits_degeneracy_by_injector_operation(tmp_path):
    # `replace` destroys the original statement, so deleting the injected line
    # compiles; `insert` leaves it intact.  The split must be visible.
    _audit(tmp_path, "fuzzlang-seed42", "heldout_project", [
        _row("ins0"), _row("ins1"),
        _row("rep0", degenerate=True), _row("rep1"),
    ])
    operations = {"ins0": "insert", "ins1": "insert",
                  "rep0": "replace", "rep1": "replace"}

    report = build_quality_report(tmp_path, operation_by_record=operations)
    by_op = report["cohorts"]["heldout_project"]["arms"]["fuzzlang"]["by_operation"]

    assert by_op["insert"] == {"fixes": 2, "degenerate": 0, "degenerate_share": 0.0}
    assert by_op["replace"] == {"fixes": 2, "degenerate": 1, "degenerate_share": 0.5}


def test_instances_that_did_not_compile_are_excluded_from_the_rate(tmp_path):
    _audit(tmp_path, "base", "eval_unseen_tu",
           [_row("r0"), _row("r1", compile_ok=False, degenerate=True)])

    arm = build_quality_report(tmp_path, operation_by_record={})[
        "cohorts"]["eval_unseen_tu"]["arms"]["base"]

    assert arm["verified_fixes_mean"] == 1.0
    assert arm["degenerate_mean"] == 0.0


def test_report_counts_identity_predictions_over_every_parsed_output(tmp_path):
    # An arm trained on one-character repairs collapses to "echo the input".
    # That failure is invisible in the fix rate -- the no-ops simply do not
    # compile -- so it is counted over all parsed predictions, not over fixes.
    _audit(tmp_path, "mechanical-seed42", "heldout_project", [
        _row("r0", compile_ok=False, edit_size=0),
        _row("r1", compile_ok=False, edit_size=0),
        _row("r2", compile_ok=False, edit_size=0),
        _row("r3", edit_size=40),
    ])

    arm = build_quality_report(tmp_path, operation_by_record={})[
        "cohorts"]["heldout_project"]["arms"]["mechanical"]

    assert arm["parsed_predictions_mean"] == 4.0
    assert arm["identity_prediction_mean"] == 3.0
    assert arm["identity_prediction_share"] == pytest.approx(0.75)


def test_csv_rows_carry_one_line_per_cohort_and_arm(tmp_path):
    _audit(tmp_path, "fuzzlang-seed42", "heldout_project",
           [_row("r0"), _row("r1", degenerate=True)])
    _audit(tmp_path, "base", "heldout_project", [_row("r0")])

    report = build_quality_report(tmp_path, operation_by_record={"r0": "insert"})

    header, *rows = quality_rows(report)
    assert header[:4] == ["cohort", "arm", "seeds", "verified_fixes_mean"]
    assert [row[1] for row in rows] == ["base", "fuzzlang"]

    op_header, *op_rows = operation_rows(report)
    assert op_header == ["cohort", "arm", "operation", "fixes", "degenerate",
                         "degenerate_share"]
    assert any(row[2] == "insert" for row in op_rows)


def test_edit_size_profile_reports_quartiles_of_the_reference_repair():
    # The size of the repair an arm teaches decides what the model learns. An
    # arm whose every example is a one-character fix teaches the identity map.
    profile = edit_size_profile([2, 2, 2, 2, 2, 2, 2, 2])
    assert profile == {"n": 8, "p25": 2, "p50": 2, "p75": 2, "zero": 0}

    spread = edit_size_profile([0, 10, 20, 30, 40, 50, 60, 70])
    assert spread["n"] == 8 and spread["zero"] == 1
    assert spread["p25"] < spread["p50"] < spread["p75"]

    assert edit_size_profile([]) == {"n": 0, "p25": None, "p50": None,
                                     "p75": None, "zero": 0}
