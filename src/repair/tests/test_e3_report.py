from __future__ import annotations

import json

import pytest

from repair.e3_report import build_e3_report, parse_eval_filename


def test_filename_parsing_separates_arm_seed_and_cohort():
    assert parse_eval_filename("fuzzlang-seed42--heldout_project.json") == (
        "fuzzlang", "42", "heldout_project",
    )
    assert parse_eval_filename("base--eval_unseen_tu.json") == (
        "base", None, "eval_unseen_tu",
    )
    with pytest.raises(ValueError):
        parse_eval_filename("no-cohort-suffix.json")


def _write(directory, config, cohort, rows):
    (directory / f"{config}--{cohort}.json").write_text(json.dumps({"n": len(rows)}))
    (directory / f"{config}--{cohort}.instances.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows)
    )


def _rows(fixed: int, total: int = 10, project: str = "abseil", language: str = "c++"):
    return [
        {
            "record_id": f"r{n}", "compile_ok": n < fixed,
            "exact_match": n < fixed // 2, "parse_ok": True,
            "project": project, "language": language,
        }
        for n in range(total)
    ]


def test_report_aggregates_seeds_and_pairs_against_base(tmp_path):
    _write(tmp_path, "base", "heldout_project", _rows(1))
    for seed, fixed in (("42", 5), ("1337", 6), ("20260808", 4)):
        _write(tmp_path, f"fuzzlang-seed{seed}", "heldout_project", _rows(fixed))
        _write(tmp_path, f"mechanical-seed{seed}", "heldout_project", _rows(2))

    report = build_e3_report(tmp_path, bootstrap_samples=200, seed=1)
    table = {r["arm"]: r for r in report["cohorts"]["heldout_project"]["table"]}

    assert table["fuzzlang"]["seeds"] == ["1337", "20260808", "42"]
    assert table["fuzzlang"]["verified_fix_rate_mean"] == 0.5
    assert table["fuzzlang"]["verified_fix_rate_std"] > 0
    # Paired against base on identical records, not pooled averages.
    assert table["fuzzlang"]["vs_base"]["paired_instances"] == 10
    assert table["fuzzlang"]["vs_base"]["mean_difference"] > 0
    assert table["fuzzlang"]["vs_mechanical"]["wins"] >= 1
    assert table["base"]["verified_fix_rate_std"] == 0.0


def test_report_breaks_the_unseen_project_cohort_out_by_project_and_language(tmp_path):
    rows = _rows(3, 6, project="abseil") + _rows(0, 6, project="ffmpeg", language="c")
    for n, row in enumerate(rows):
        row["record_id"] = f"r{n}"
    _write(tmp_path, "fuzzlang-seed42", "heldout_project", rows)

    report = build_e3_report(tmp_path, bootstrap_samples=100, seed=1)
    entry = report["cohorts"]["heldout_project"]["table"][0]

    assert entry["by_project"]["abseil"]["verified_fix_rate"] == 0.5
    assert entry["by_project"]["ffmpeg"]["verified_fix_rate"] == 0.0
    assert set(entry["by_language"]) == {"c", "c++"}
