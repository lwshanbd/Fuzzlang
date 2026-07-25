#!/usr/bin/env python3
"""Split archived code-witness requests into bounded, auditable campaigns."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        for row in rows
    ))


def split_requests(
    rows: Sequence[dict[str, Any]],
    *,
    output_root: Path,
    label_start: int,
    batch_size: int,
    campaign: str,
) -> dict[str, int]:
    """Write non-overlapping request batches without changing their evidence."""
    if label_start < 0 or batch_size <= 0:
        raise ValueError("label_start must be non-negative and batch_size positive")
    if not campaign:
        raise ValueError("campaign must be non-empty")
    if any(not isinstance(row.get("diag_name"), str) or not row["diag_name"] for row in rows):
        raise ValueError("each request requires a non-empty diag_name")
    chunks = [rows[offset:offset + batch_size] for offset in range(0, len(rows), batch_size)]
    for index, chunk in enumerate(chunks):
        label = label_start + index
        directory = output_root / f"coverage-first-v{label:04d}"
        requests = directory / "requests.jsonl"
        manifest = directory / "request-manifest.json"
        if requests.exists() or manifest.exists():
            raise FileExistsError(f"refusing to overwrite existing batch {label:04d}")
        _write_jsonl(requests, chunk)
        manifest.write_text(json.dumps({
            "schema": "fuzzlang.coverage_first_code_witness_requests",
            "llvm_version": "llvmorg-22.1.8",
            "campaign": campaign,
            "counts": {
                "requests": len(chunk),
                "targets_with_emission_evidence": sum(
                    row.get("emission_evidence") is not None for row in chunk
                ),
            },
            "target_diagnostics": [row["diag_name"] for row in chunk],
        }, sort_keys=True) + "\n")
    return {
        "batches": len(chunks),
        "requests": len(rows),
        "first_label": label_start if chunks else 0,
        "last_label": label_start + len(chunks) - 1 if chunks else 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--label-start", type=int, required=True)
    parser.add_argument("--batch-size", type=int, default=12)
    parser.add_argument("--campaign", required=True)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.requests.read_text().splitlines() if line.strip()]
    print(json.dumps(split_requests(
        rows,
        output_root=args.output_root,
        label_start=args.label_start,
        batch_size=args.batch_size,
        campaign=args.campaign,
    ), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
