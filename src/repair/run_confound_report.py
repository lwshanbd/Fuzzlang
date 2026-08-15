#!/usr/bin/env python3
"""Check whether E3's per-project breakdown measures the project.

Joins each evaluation instance to its project and target diagnostic, reports how
far the two can be separated at all, and predicts each project's rate from the
pooled per-diagnostic rates. A residual near zero means the per-project table is
reporting diagnostic composition under a project's name.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Sequence

from repair.confound_analysis import adjusted_rate, stratum_overlap
from repair.e3_report import parse_eval_filename


def _cohort_index(path: Path) -> dict[str, tuple[str, str]]:
    index: dict[str, tuple[str, str]] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        detail = (record.get("provenance") or {}).get("detail") or {}
        index[str(record["record_id"])] = (
            str(detail.get("project") or "?"), str(detail.get("target_diag") or "?"),
        )
    return index


def _write_csv(path: Path, rows: Sequence[Sequence[object]]) -> None:
    with path.open("w", newline="") as stream:
        csv.writer(stream).writerows(rows)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-dir", required=True)
    parser.add_argument("--cohort", action="append", required=True,
                        metavar="NAME=PATH")
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args(argv)

    cohorts = {}
    for spec in args.cohort:
        name, _, path = spec.partition("=")
        if not path:
            parser.error(f"--cohort expects NAME=PATH, got {spec!r}")
        cohorts[name] = _cohort_index(Path(path))

    overlap_rows: list[list[object]] = [[
        "cohort", "instances", "projects", "diagnostics",
        "project_exclusive_diagnostics", "instances_with_shared_diagnostic",
        "separable_fraction", "median_instances_per_diagnostic",
    ]]
    adjusted_rows: list[list[object]] = [[
        "cohort", "arm", "project", "instances", "observed",
        "predicted_from_diagnostic_mix", "residual",
    ]]

    for cohort, index in sorted(cohorts.items()):
        overlap = stratum_overlap(
            [{"group": project, "stratum": diagnostic}
             for project, diagnostic in index.values()]
        )
        overlap_rows.append([
            cohort, overlap["instances"], overlap["groups"], overlap["strata"],
            overlap["group_exclusive_strata"],
            overlap["instances_with_shared_stratum"],
            overlap["separable_fraction"],
            overlap["median_instances_per_stratum"],
        ])

        by_arm: dict[str, dict[tuple[str, str], list[int]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for path in sorted(Path(args.eval_dir).glob(f"*--{cohort}.json")):
            arm, _, _ = parse_eval_filename(path.name)
            companion = Path(str(path)[: -len(".json")] + ".instances.jsonl")
            if not companion.is_file():
                continue
            for line in companion.read_text().splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                key = index.get(str(row.get("record_id")))
                if key is None:
                    continue
                by_arm[arm][key].append(int(bool(row.get("compile_ok"))))

        for arm, outcomes in sorted(by_arm.items()):
            for project in sorted({project for project, _ in outcomes}):
                result = adjusted_rate(outcomes, group=project)
                adjusted_rows.append([
                    cohort, arm, project, result["instances"], result["observed"],
                    result["predicted_from_strata"], result["residual"],
                ])

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write_csv(out / "project_diagnostic_overlap.csv", overlap_rows)
    _write_csv(out / "project_rates_adjusted.csv", adjusted_rows)
    for rows in (overlap_rows, adjusted_rows):
        for row in rows:
            print("  ".join(str(cell) for cell in row))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
