#!/usr/bin/env python3
"""Turn per-instance edit-quality audits into the E3 behaviour table.

Reads the output directory of ``run_quality_audit.py``, joins each evaluated
record to the injector operation that built it, and writes the CSVs the paper
quotes plus the full JSON.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Sequence

from repair.eval.edit_quality import compute_edit_quality
from repair.quality_report import (
    build_quality_report,
    edit_size_profile,
    injector_operations,
    operation_rows,
    quality_rows,
    record_operations,
)
from repair.sft_data import make_localized_repair_example


def _load_jsonl(path: str | Path) -> list[dict]:
    return [
        json.loads(line)
        for line in Path(path).read_text().splitlines()
        if line.strip()
    ]


def _write_csv(path: Path, rows: Sequence[Sequence[object]]) -> None:
    with path.open("w", newline="") as stream:
        csv.writer(stream).writerows(rows)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-dir", required=True)
    parser.add_argument(
        "--cohort", action="append", default=[], metavar="PATH",
        help="Cohort record JSONL; repeat once per cohort.",
    )
    parser.add_argument(
        "--injector-library",
        help="Replay library used to attribute each record to an edit operation.",
    )
    parser.add_argument(
        "--train-arm", action="append", default=[], metavar="NAME=PATH",
        help="Training JSONL of one arm; profiles the repair size it teaches.",
    )
    parser.add_argument("--out-dir", required=True)
    return parser.parse_args(argv)


def _train_profile_rows(specs: Sequence[str]) -> list[list[object]]:
    rows: list[list[object]] = [
        ["arm", "records", "gold_edit_p25", "gold_edit_p50", "gold_edit_p75",
         "gold_edit_zero", "skipped"]
    ]
    for spec in specs:
        name, _, path = spec.partition("=")
        if not path:
            raise ValueError(f"--train-arm expects NAME=PATH, got {spec!r}")
        sizes: list[int] = []
        skipped = 0
        for record in _load_jsonl(path):
            try:
                example = make_localized_repair_example(record)
                gold = example.target.apply(example.source_window)
                sizes.append(
                    compute_edit_quality(example.source_window, gold, gold)[
                        "gold_edit_size"
                    ]
                )
            except (KeyError, ValueError):
                skipped += 1
        profile = edit_size_profile(sizes)
        rows.append([
            name, profile["n"], profile["p25"], profile["p50"], profile["p75"],
            profile["zero"], skipped,
        ])
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    operations = (
        injector_operations(args.injector_library) if args.injector_library else {}
    )
    by_record: dict[str, str] = {}
    for cohort_path in args.cohort:
        by_record.update(record_operations(_load_jsonl(cohort_path), operations))

    report = build_quality_report(args.audit_dir, operation_by_record=by_record)
    report["inputs"] = {
        "audit_dir": args.audit_dir,
        "cohorts": list(args.cohort),
        "injector_library": args.injector_library,
    }

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "quality-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    _write_csv(out / "behaviour_audit.csv", quality_rows(report))
    _write_csv(out / "degeneracy_by_operation.csv", operation_rows(report))
    if args.train_arm:
        profile = _train_profile_rows(args.train_arm)
        _write_csv(out / "training_edit_size.csv", profile)
        for row in profile:
            print("  ".join(str(cell) for cell in row))

    for row in quality_rows(report):
        print("  ".join(str(cell) for cell in row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
