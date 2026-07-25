#!/usr/bin/env python3
"""Recover code-witness targets not started before a bounded GPU job ended."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


def select_unattempted_requests(
    requests: Iterable[Mapping[str, Any]],
    attempts: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return request rows with no corresponding completed attempt.

    Current logs carry ``request_index``.  The diagnostic-name fallback keeps
    recovery compatible with early archived logs that predate the index.
    """
    request_rows = [dict(row) for row in requests]
    attempted_indices: set[int] = set()
    attempted_names: set[str] = set()
    for attempt in attempts:
        index = attempt.get("request_index")
        if isinstance(index, int) and not isinstance(index, bool):
            attempted_indices.add(index)
            continue
        name = attempt.get("diag_name")
        if isinstance(name, str) and name:
            attempted_names.add(name)
    return [
        row for index, row in enumerate(request_rows)
        if index not in attempted_indices
        and row.get("diag_name") not in attempted_names
    ]


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: row must be an object")
        result.append(value)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--attempts", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--manifest-out", type=Path, required=True)
    args = parser.parse_args()
    requests = _load_jsonl(args.requests)
    attempts = _load_jsonl(args.attempts)
    remaining = select_unattempted_requests(requests, attempts)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        for row in remaining
    ))
    manifest = {
        "schema": "fuzzlang.unattempted_code_witness_recovery",
        "schema_version": 1,
        "counts": {
            "input_requests": len(requests),
            "attempt_rows": len(attempts),
            "unattempted_requests": len(remaining),
        },
    }
    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_out.write_text(json.dumps(manifest, sort_keys=True) + "\n")
    print(json.dumps(manifest["counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
