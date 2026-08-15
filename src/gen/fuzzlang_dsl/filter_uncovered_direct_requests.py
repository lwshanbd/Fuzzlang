#!/usr/bin/env python3
"""Remove already-covered targets before a direct FuzzLang-Injector wave.

The direct-DSL route is deliberately scheduled after other long-running
campaigns.  Its target list must therefore be refreshed against the frozen
audit that precedes it, rather than wasting a large local-model allocation on
a diagnostic that a preceding replay has already covered.  Clang tests remain
prompt-only trigger evidence; the witness rows are still real, clean-gated
production source requests.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4


TEST_EVIDENCE_MARKER = "Regression-test trigger evidence"


def _atomic_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
    )
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(payload)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _rows(path: Path) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{line_number}: invalid JSON") from error
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: expected a JSON object")
        values.append(value)
    return values


def _diag_name(row: dict[str, Any], *, kind: str) -> str:
    name = row.get("diag_name")
    if not isinstance(name, str) or not name:
        raise ValueError(f"{kind} row lacks a non-empty diag_name")
    return name


def _has_test_evidence(row: dict[str, Any]) -> bool:
    evidence = row.get("emission_evidence", row.get("evidence"))
    if isinstance(evidence, str):
        return TEST_EVIDENCE_MARKER in evidence
    if isinstance(evidence, dict):
        return TEST_EVIDENCE_MARKER in str(evidence.get("emission_evidence", ""))
    return False


def filter_uncovered_direct_requests(
    direct_requests: Iterable[dict[str, Any]],
    witness_requests: Iterable[dict[str, Any]],
    *,
    covered_diagnostic_names: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Keep only current strict gaps, preserving all matching real witnesses."""
    direct_rows = list(direct_requests)
    witness_rows = list(witness_requests)
    direct_names = [_diag_name(row, kind="direct request") for row in direct_rows]
    if len(set(direct_names)) != len(direct_names):
        raise ValueError("direct request input has duplicate diagnostic targets")

    remaining_direct: list[dict[str, Any]] = []
    missing_test_evidence_removed = 0
    for row, name in zip(direct_rows, direct_names, strict=True):
        if name in covered_diagnostic_names:
            continue
        if not _has_test_evidence(row):
            # The direct runner has the same hard gate.  Filtering here keeps
            # a scheduled GPU shard honest about its useful target count and
            # prevents an evidence-less row from occupying a shard slot.
            missing_test_evidence_removed += 1
            continue
        remaining_direct.append(row)

    remaining_names = {_diag_name(row, kind="direct request") for row in remaining_direct}
    remaining_witnesses = [
        row for row in witness_rows
        if _diag_name(row, kind="witness request") in remaining_names
    ]
    witnessed_names = {
        _diag_name(row, kind="witness request") for row in remaining_witnesses
    }
    missing_witnesses = sorted(remaining_names - witnessed_names)
    if missing_witnesses:
        raise ValueError(
            "remaining direct target has no matching real-source witness: "
            + ", ".join(missing_witnesses)
        )
    return remaining_direct, remaining_witnesses, {
        "input_direct_targets": len(direct_rows),
        "covered_targets_removed": sum(
            name in covered_diagnostic_names for name in direct_names
        ),
        "missing_test_evidence_removed": missing_test_evidence_removed,
        "remaining_direct_targets": len(remaining_direct),
        "remaining_witness_requests": len(remaining_witnesses),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--direct-requests", type=Path, required=True)
    parser.add_argument("--witness-requests", type=Path, required=True)
    parser.add_argument("--direct-out", type=Path, required=True)
    parser.add_argument("--witness-out", type=Path, required=True)
    parser.add_argument("--manifest-out", type=Path, required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    audit = json.loads(args.audit.read_text())
    covered = audit.get("verified_diagnostic_names")
    if not isinstance(covered, list) or not all(isinstance(name, str) for name in covered):
        raise ValueError(f"{args.audit}: expected verified_diagnostic_names string list")
    direct, witnesses, manifest = filter_uncovered_direct_requests(
        _rows(args.direct_requests), _rows(args.witness_requests),
        covered_diagnostic_names=set(covered),
    )
    _atomic_jsonl(args.direct_out, direct)
    _atomic_jsonl(args.witness_out, witnesses)
    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_out.write_text(json.dumps({
        "schema": "fuzzlang.filtered_direct_injector_requests.v1",
        "audit": str(args.audit),
        "source_direct_requests": str(args.direct_requests),
        "source_witness_requests": str(args.witness_requests),
        **manifest,
    }, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
