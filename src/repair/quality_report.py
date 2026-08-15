"""Aggregate per-instance edit-quality audits into the behaviour table.

A ``verified fix`` in E3 means the patched Clang accepted the repaired
translation unit.  That is a necessary condition, not a sufficient one: a model
can delete the offending line and compile cleanly while destroying the
program's meaning.  :mod:`repair.eval.edit_quality` flags such outputs per
instance; this module turns those flags into the numbers the paper quotes.

Two reporting rules are load-bearing:

* rates are averaged **over seeds** rather than pooled over instances, so a
  seed that happens to fix more instances does not dominate the share;
* degeneracy is broken out **by injector operation**, because an injection that
  ``replace``\\ s a statement erases the original text from the window and
  leaves the repair genuinely under-determined -- deleting the injected line is
  then a compiling answer.  An ``insert`` leaves the original intact.  Reporting
  one blended number would hide a property of the task behind a property of the
  model.
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from repair.e3_report import parse_eval_filename

UNKNOWN_OPERATION = "unknown"

# Audit flags that make a compiling output suspect, in the order reported.
DEGENERACY_FLAGS = (
    "pure_line_deletion",
    "large_deletion",
    "excessive_edit",
    "empty_repair",
)


def injector_operations(library_path: str | Path) -> dict[str, str]:
    """Map each injector in the replay library to its edit operation."""
    operations: dict[str, str] = {}
    with Path(library_path).open() as stream:
        for line in stream:
            if not line.strip():
                continue
            entry = json.loads(line)
            injector_id = entry.get("injector_id")
            if injector_id:
                operations[str(injector_id)] = str(
                    (entry.get("edit") or {}).get("operation") or UNKNOWN_OPERATION
                )
    return operations


def record_operations(
    records: Iterable[Mapping[str, Any]], operations: Mapping[str, str],
) -> dict[str, str]:
    """Join dataset records to injector operations through ``injector_id``."""
    joined: dict[str, str] = {}
    for record in records:
        detail = (record.get("provenance") or {}).get("detail") or {}
        injector_id = detail.get("injector_id")
        joined[str(record.get("record_id"))] = operations.get(
            str(injector_id), UNKNOWN_OPERATION
        )
    return joined


def edit_size_profile(sizes: Iterable[int]) -> dict[str, Any]:
    """Quartiles of a set of reference-repair sizes, in diff characters.

    The distribution an arm trains on is what the model imitates: an arm whose
    reference repair is one character wide teaches "echo the input", which
    minimises loss and fixes nothing.
    """
    ordered = sorted(sizes)
    if not ordered:
        return {"n": 0, "p25": None, "p50": None, "p75": None, "zero": 0}
    return {
        "n": len(ordered),
        "p25": ordered[len(ordered) // 4],
        "p50": ordered[len(ordered) // 2],
        "p75": ordered[(3 * len(ordered)) // 4],
        "zero": sum(1 for size in ordered if size == 0),
    }


def _load_instances(path: Path) -> list[dict]:
    companion = Path(str(path)[: -len(".json")] + ".instances.jsonl")
    if not companion.is_file():
        return []
    return [
        json.loads(line) for line in companion.read_text().splitlines() if line.strip()
    ]


def _is_degenerate(row: Mapping[str, Any]) -> bool:
    quality = row.get("quality") or {}
    if quality.get("degenerate") is not None:
        return bool(quality["degenerate"])
    return any(bool(quality.get(flag)) for flag in DEGENERACY_FLAGS)


def _flag_totals(fixes: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {
        flag: sum(bool((row.get("quality") or {}).get(flag)) for row in fixes)
        for flag in DEGENERACY_FLAGS
    }


def _edit_sizes(fixes: Sequence[Mapping[str, Any]]) -> list[int]:
    return [
        int((row.get("quality") or {})["predicted_edit_size"])
        for row in fixes
        if (row.get("quality") or {}).get("predicted_edit_size") is not None
    ]


def build_quality_report(
    audit_dir: str | Path,
    *,
    operation_by_record: Mapping[str, str],
) -> dict:
    """Assemble the per-cohort, per-arm behaviour table from audit outputs."""
    by_cohort: dict[str, dict[str, dict[str | None, list[dict]]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    for path in sorted(Path(audit_dir).glob("*--*.json")):
        arm, seed, cohort = parse_eval_filename(path.name)
        by_cohort[cohort][arm][seed] = _load_instances(path)

    report: dict = {"schema": "fuzzlang.quality_report.v1", "cohorts": {}}
    for cohort, arms in sorted(by_cohort.items()):
        entries: dict[str, dict] = {}
        for arm, seeds in sorted(arms.items()):
            per_seed_fixes: list[int] = []
            per_seed_degenerate: list[int] = []
            per_seed_parsed: list[int] = []
            per_seed_identity: list[int] = []
            pooled_fixes: list[dict] = []
            for rows in seeds.values():
                fixes = [row for row in rows if row.get("compile_ok")]
                per_seed_fixes.append(len(fixes))
                per_seed_degenerate.append(sum(_is_degenerate(row) for row in fixes))
                pooled_fixes.extend(fixes)
                parsed = [row for row in rows if (row.get("quality") or {})]
                per_seed_parsed.append(len(parsed))
                per_seed_identity.append(
                    sum(
                        (row["quality"].get("predicted_edit_size") or 0) == 0
                        for row in parsed
                    )
                )

            fixes_mean = statistics.fmean(per_seed_fixes) if per_seed_fixes else 0.0
            degenerate_mean = (
                statistics.fmean(per_seed_degenerate) if per_seed_degenerate else 0.0
            )
            share = degenerate_mean / fixes_mean if fixes_mean else 0.0
            parsed_mean = statistics.fmean(per_seed_parsed) if per_seed_parsed else 0.0
            identity_mean = (
                statistics.fmean(per_seed_identity) if per_seed_identity else 0.0
            )

            by_operation: dict[str, dict] = {}
            grouped: dict[str, list[dict]] = defaultdict(list)
            for row in pooled_fixes:
                grouped[
                    operation_by_record.get(
                        str(row.get("record_id")), UNKNOWN_OPERATION
                    )
                ].append(row)
            for operation, rows in sorted(grouped.items()):
                degenerate = sum(_is_degenerate(row) for row in rows)
                by_operation[operation] = {
                    "fixes": len(rows),
                    "degenerate": degenerate,
                    "degenerate_share": round(degenerate / len(rows), 4),
                }

            sizes = sorted(_edit_sizes(pooled_fixes))
            entries[arm] = {
                "arm": arm,
                "seeds": sorted(s for s in seeds if s is not None) or ["n/a"],
                "verified_fixes_mean": round(fixes_mean, 4),
                "degenerate_mean": round(degenerate_mean, 4),
                "degenerate_share": round(share, 4),
                "nondegenerate_share": round(1.0 - share, 4),
                "parsed_predictions_mean": round(parsed_mean, 4),
                "identity_prediction_mean": round(identity_mean, 4),
                "identity_prediction_share": (
                    round(identity_mean / parsed_mean, 4) if parsed_mean else 0.0
                ),
                "flags": _flag_totals(pooled_fixes),
                "edit_size_median": (
                    statistics.median(sizes) if sizes else None
                ),
                "by_operation": by_operation,
            }
        report["cohorts"][cohort] = {"arms": entries}
    return report


def quality_rows(report: Mapping[str, Any]) -> list[list[Any]]:
    """CSV rows: one line per cohort and arm."""
    header = [
        "cohort", "arm", "seeds", "verified_fixes_mean", "degenerate_mean",
        "degenerate_share", "nondegenerate_share", "edit_size_median",
        "identity_prediction_share", *DEGENERACY_FLAGS,
    ]
    rows: list[list[Any]] = [header]
    for cohort, block in sorted(report.get("cohorts", {}).items()):
        for arm, entry in sorted(block["arms"].items()):
            rows.append([
                cohort, arm, "|".join(entry["seeds"]),
                entry["verified_fixes_mean"], entry["degenerate_mean"],
                entry["degenerate_share"], entry["nondegenerate_share"],
                entry["edit_size_median"], entry["identity_prediction_share"],
                *(entry["flags"][flag] for flag in DEGENERACY_FLAGS),
            ])
    return rows


def operation_rows(report: Mapping[str, Any]) -> list[list[Any]]:
    """CSV rows: degeneracy split by the injector operation that built the task."""
    rows: list[list[Any]] = [
        ["cohort", "arm", "operation", "fixes", "degenerate", "degenerate_share"]
    ]
    for cohort, block in sorted(report.get("cohorts", {}).items()):
        for arm, entry in sorted(block["arms"].items()):
            for operation, stats in sorted(entry["by_operation"].items()):
                rows.append([
                    cohort, arm, operation, stats["fixes"],
                    stats["degenerate"], stats["degenerate_share"],
                ])
    return rows
