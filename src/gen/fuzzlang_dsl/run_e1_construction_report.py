#!/usr/bin/env python3
"""Aggregate the E1 library-replay arms into the reach-and-cost table.

E1's claim is a cost/reach sentence, not a contest: applying the released
Injector library to real source — including projects it has never seen —
produces N compiler-verified paired records over K diagnostics using zero GPU
hours and zero model tokens. This assembles exactly that table.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from gen.fuzzlang_dsl.e1_report import replay_arm_summary

ARMS = ("lexical", "append")
SPLITS = ("train", "eval_unseen_tu", "heldout_project")


def _load(run_dir: Path) -> dict[tuple[str, str], dict]:
    loaded: dict[tuple[str, str], dict] = {}
    for operations in ARMS:
        for split in SPLITS:
            manifest = run_dir / f"{operations}-{split}" / "manifest.json"
            if manifest.is_file():
                loaded[(operations, split)] = json.loads(manifest.read_text())
    return loaded


def _amortization(run_dir: Path, operations: str, split: str) -> dict:
    """How far one Injector reaches, which is the whole reuse argument."""
    path = run_dir / f"{operations}-{split}" / "injector_reach.json"
    if not path.is_file():
        return {}
    reach = json.loads(path.read_text())
    if not reach:
        return {}
    sources = sorted((entry["sources"] for entry in reach.values()), reverse=True)
    projects = [len(entry["projects"]) for entry in reach.values()]
    return {
        "injectors_with_a_record": len(reach),
        "sources_per_injector_mean": round(sum(sources) / len(sources), 3),
        "sources_per_injector_max": sources[0],
        "injectors_reaching_multiple_sources": sum(1 for n in sources if n > 1),
        "injectors_reaching_multiple_projects": sum(1 for n in projects if n > 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument(
        "--canonical-map", type=Path,
        help="diagnostic_record_map.csv; diagnostics absent from it are new",
    )
    parser.add_argument("--report-out", type=Path, required=True)
    parser.add_argument("--table-out", type=Path)
    parser.add_argument("--per-project-out", type=Path)
    parser.add_argument(
        "--exclude-vendored", action="store_true",
        help=(
            "Recount every arm from its records with fetched-dependency source "
            "dropped. duckdb and protobuf vendor Abseil under build/_deps, so "
            "the manifests written at generation time attribute that source to "
            "the project that fetched it."
        ),
    )
    args = parser.parse_args()

    manifests = _load(args.run_dir)
    if not manifests:
        raise SystemExit(f"no completed arms under {args.run_dir}")
    covered: set[str] = set()
    if args.canonical_map is not None:
        covered = {
            row["diag_name"]
            for row in csv.DictReader(args.canonical_map.read_text().splitlines())
        }

    table = []
    per_project_rows = []
    for (operations, split), manifest in sorted(manifests.items()):
        summary = manifest["summary"]
        arm_dir = args.run_dir / f"{operations}-{split}"
        diagnostics = _diagnostics(arm_dir)
        recount: dict = {}
        if args.exclude_vendored:
            recount = replay_arm_summary(
                _records(arm_dir), exclude_vendored=True,
            )
            diagnostics = set(recount["diagnostic_names"])
        counts_source = recount or summary
        reach = (
            {key: recount[key] for key in (
                "injectors_with_a_record", "sources_per_injector_mean",
                "sources_per_injector_max",
                "injectors_reaching_multiple_sources",
                "injectors_reaching_multiple_projects",
            )}
            if recount else _amortization(args.run_dir, operations, split)
        )
        table.append({
            "operations": operations,
            "split": split,
            "sources_scanned": summary["sources_scanned"],
            "library_injectors": summary["library_injectors"],
            "records": counts_source["records"],
            "diagnostics": counts_source["diagnostics"],
            "projects": counts_source["projects"],
            "source_tus": counts_source["source_tus"],
            "excluded_vendored_records": recount.get("excluded_vendored", 0),
            "new_vs_canonical_diagnostics": len(diagnostics - covered),
            "model_calls": manifest["model_calls"],
            "gpu_hours": 0.0,
            "compiler_invocations": summary["budget"]["compiler_invocations"],
            "compiler_invocations_per_record": summary["compiler_invocations_per_record"],
            "wall_seconds": summary["wall_seconds"],
            **reach,
        })
        for project, counts in counts_source.get("per_project_records", {}).items():
            per_project_rows.append({
                "operations": operations, "split": split, "project": project,
                **counts,
            })

    report = {
        "schema": "fuzzlang.e1_construction_report.v1",
        "claim": (
            "Applying the released FuzzLang Injector library to clean, non-test "
            "real-project source produces compiler-verified paired records using "
            "zero GPU hours and zero model tokens."
        ),
        "zero_model_calls_everywhere": all(
            manifest["model_calls"] == 0 for manifest in manifests.values()
        ),
        "table": table,
        "per_project": per_project_rows,
    }
    args.report_out.parent.mkdir(parents=True, exist_ok=True)
    args.report_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    if args.table_out is not None:
        _write_csv(args.table_out, table)
    if args.per_project_out is not None and per_project_rows:
        _write_csv(args.per_project_out, per_project_rows)
    print(json.dumps({
        "zero_model_calls_everywhere": report["zero_model_calls_everywhere"],
        "table": table,
    }, indent=2, sort_keys=True))
    return 0


def _records(arm_dir: Path) -> list[dict]:
    path = arm_dir / "records.jsonl"
    if not path.is_file():
        return []
    return [
        json.loads(line) for line in path.read_text().splitlines() if line.strip()
    ]


def _diagnostics(arm_dir: Path) -> set[str]:
    records = arm_dir / "records.jsonl"
    if not records.is_file():
        return set()
    return {
        json.loads(line)["provenance"]["detail"]["target_diag"]
        for line in records.read_text().splitlines() if line.strip()
    }


def _write_csv(path: Path, rows: list[dict]) -> None:
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
