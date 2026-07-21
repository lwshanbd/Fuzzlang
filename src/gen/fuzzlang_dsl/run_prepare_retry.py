#!/usr/bin/env python3
"""Prepare a deterministic local retry-request file from archived attempts."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from gen.fuzzlang_dsl.retry import load_json_rows, select_retry_requests


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _write_jsonl(path: Path, values: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(_canonical_json(value) + "\n" for value in values)
    path.write_text(payload)
    return payload.count("\n")


def _file_info(path: Path, *, rows: int | None = None) -> dict[str, Any]:
    payload = path.read_bytes()
    value: dict[str, Any] = {
        "path": str(path),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    if rows is not None:
        value["records"] = rows
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--attempts", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--manifest-out", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output_paths = {args.out.resolve(), args.manifest_out.resolve()}
    if len(output_paths) != 2:
        raise ValueError("out and manifest-out must be distinct")
    if output_paths & {args.requests.resolve(), args.attempts.resolve()}:
        raise ValueError("retry outputs must not overwrite inputs")

    requests = load_json_rows(args.requests)
    attempts = load_json_rows(args.attempts)
    selected, summary = select_retry_requests(requests, attempts)
    rows = _write_jsonl(args.out, selected)
    manifest = {
        "schema": "fuzzlang.synthesis_retry_selection",
        "schema_version": 1,
        "uses_llm_api": False,
        "selection": summary,
        "inputs": {
            "requests": _file_info(args.requests, rows=len(requests)),
            "attempts": _file_info(args.attempts, rows=len(attempts)),
        },
        "outputs": {"requests": _file_info(args.out, rows=rows)},
    }
    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_out.write_text(_canonical_json(manifest) + "\n")
    print(f"[prepare-retry] requests={rows} uses_llm_api=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
