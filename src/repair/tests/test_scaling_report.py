from __future__ import annotations

import json

import pytest

from repair.scaling_report import (
    build_scaling_report,
    parse_scaling_arm,
    scaling_rows,
)


def _write(directory, config, cohort, fixed, total=10):
    rows = [
        {"record_id": f"r{n}", "compile_ok": n < fixed, "parse_ok": True,
         "exact_match": n < fixed // 2}
        for n in range(total)
    ]
    (directory / f"{config}--{cohort}.json").write_text(json.dumps({"n": total}))
    (directory / f"{config}--{cohort}.instances.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows)
    )


def test_arm_name_carries_the_training_size():
    assert parse_scaling_arm("fuzzlang4000") == ("fuzzlang", 4000)
    assert parse_scaling_arm("fuzzlang557") == ("fuzzlang", 557)
    assert parse_scaling_arm("base") == ("base", None)


def test_report_orders_tiers_by_size_and_reports_the_increment(tmp_path):
    # The curve is only readable if the tiers are ordered by training size and
    # each step states what the extra data bought.
    _write(tmp_path, "base", "heldout_project", 1)
    _write(tmp_path, "fuzzlang557-seed42", "heldout_project", 5)
    _write(tmp_path, "fuzzlang1500-seed42", "heldout_project", 7)
    _write(tmp_path, "fuzzlang4000-seed42", "heldout_project", 8)

    report = build_scaling_report(tmp_path, bootstrap_samples=200, seed=1)
    curve = report["cohorts"]["heldout_project"]["curve"]

    assert [point["training_records"] for point in curve] == [557, 1500, 4000]
    assert [point["verified_fix_rate"] for point in curve] == [0.5, 0.7, 0.8]
    # Each step is measured against the previous tier, not against the base.
    assert curve[0]["delta_vs_previous"] is None
    assert curve[1]["delta_vs_previous"] == pytest.approx(0.2)
    assert curve[2]["delta_vs_previous"] == pytest.approx(0.1)
    assert report["cohorts"]["heldout_project"]["base_rate"] == 0.1


def test_base_model_is_reported_but_never_placed_on_the_curve(tmp_path):
    _write(tmp_path, "base", "eval_unseen_tu", 2)
    _write(tmp_path, "fuzzlang557-seed42", "eval_unseen_tu", 5)

    cohort = build_scaling_report(tmp_path, bootstrap_samples=100, seed=1)[
        "cohorts"]["eval_unseen_tu"]

    assert [point["training_records"] for point in cohort["curve"]] == [557]
    assert cohort["base_rate"] == 0.2


def test_seeds_of_one_tier_are_averaged(tmp_path):
    _write(tmp_path, "fuzzlang557-seed42", "heldout_project", 4)
    _write(tmp_path, "fuzzlang557-seed7", "heldout_project", 6)

    point = build_scaling_report(tmp_path, bootstrap_samples=100, seed=1)[
        "cohorts"]["heldout_project"]["curve"][0]

    assert point["seeds"] == ["42", "7"]
    assert point["verified_fix_rate"] == pytest.approx(0.5)


def test_csv_rows_carry_one_line_per_cohort_and_tier(tmp_path):
    _write(tmp_path, "fuzzlang557-seed42", "heldout_project", 5)
    _write(tmp_path, "fuzzlang1500-seed42", "heldout_project", 7)

    header, *rows = scaling_rows(
        build_scaling_report(tmp_path, bootstrap_samples=100, seed=1)
    )

    assert header[:3] == ["cohort", "training_records", "verified_fix_rate"]
    assert [int(row[1]) for row in rows] == [557, 1500]
