#!/usr/bin/env python3
"""Produce the E1 metric table, failure modes, and coverage delta from a run."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from gen.fuzzlang_dsl.e1_report import build_e1_report

TABLE_COLUMNS = [
    "arm", "targets", "targets_with_accepted_record", "target_hit_rate",
    "accepted_records", "records_per_target", "accepted_injectors",
    "macro_exact_target_rate", "macro_exact_target_rate_ci95",
    "macro_held_out_source_rate", "macro_cross_project_transfer_rate",
    "macro_cross_project_transfer_rate_ci95",
    "model_calls", "output_tokens", "model_seconds", "wall_seconds",
    "compiler_invocations", "records_per_1k_output_tokens",
    "records_per_gpu_hour", "output_tokens_per_accepted_record",
    "compiler_invocations_per_accepted_record",
    "model_calls_per_accepted_record", "new_strict_coverage_types",
]


def _load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [
        json.loads(line) for line in path.read_text().splitlines() if line.strip()
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument(
        "--canonical-map", type=Path,
        help="diagnostic_record_map.csv; targets absent from it count as new",
    )
    parser.add_argument("--report-out", type=Path, required=True)
    parser.add_argument("--table-out", type=Path)
    parser.add_argument("--per-target-out", type=Path)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20260807)
    args = parser.parse_args()

    comparison = json.loads((args.run_dir / "comparison.json").read_text())
    attempts = [
        row
        for arm in ("direct_edit", "injector")
        for row in _load_jsonl(args.run_dir / arm / "attempts.jsonl")
    ]
    covered: set[str] = set()
    if args.canonical_map is not None:
        covered = {
            row["diag_name"]
            for row in csv.DictReader(args.canonical_map.read_text().splitlines())
        }

    report = build_e1_report(
        comparison, attempts=attempts, covered=covered,
        bootstrap_samples=args.bootstrap_samples, seed=args.seed,
    )
    report["manifest"] = comparison.get("manifest", {})
    args.report_out.parent.mkdir(parents=True, exist_ok=True)
    args.report_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    if args.table_out is not None:
        args.table_out.parent.mkdir(parents=True, exist_ok=True)
        with args.table_out.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=TABLE_COLUMNS)
            writer.writeheader()
            for row in report["table"]:
                flat = {key: row.get(key) for key in TABLE_COLUMNS}
                flat["new_strict_coverage_types"] = row["coverage"]["new_types"]
                for key, value in list(flat.items()):
                    if isinstance(value, (list, tuple)):
                        flat[key] = (
                            f"[{value[0]}, {value[1]}]" if value else ""
                        )
                writer.writerow(flat)

    if args.per_target_out is not None:
        args.per_target_out.parent.mkdir(parents=True, exist_ok=True)
        columns = [
            "diag_name", "arm", "attempted_sources", "evidence_sources",
            "accepted_records", "exact_target_rate_per_source",
            "held_out_sources", "available_held_out_sources",
            "held_out_source_rate", "transfer_sources",
            "available_transfer_sources", "transfer_rate", "model_calls",
            "accepted_injectors", "replaying_injectors",
        ]
        with args.per_target_out.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for target, arms in sorted(report["per_target"].items()):
                for arm, stats in sorted(arms.items()):
                    row = {key: stats.get(key) for key in columns}
                    row["diag_name"], row["arm"] = target, arm
                    writer.writerow(row)

    print(json.dumps({
        "sample": report["sample"],
        "table": [
            {key: row[key] for key in (
                "arm", "targets", "accepted_records", "target_hit_rate",
                "macro_exact_target_rate", "macro_cross_project_transfer_rate",
                "model_calls", "output_tokens",
                "records_per_1k_output_tokens", "records_per_gpu_hour",
            )}
            for row in report["table"]
        ],
        "paired_difference": report["paired_difference"],
        "failure_modes": report["failure_modes"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
