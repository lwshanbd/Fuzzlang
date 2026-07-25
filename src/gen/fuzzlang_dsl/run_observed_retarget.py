#!/usr/bin/env python3
"""Prepare compiler-observed diagnostic retargets for strict replay."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from foundation.diagnostics.catalog import load_catalog
from gen.fuzzlang_dsl.campaign import load_injectors_jsonl
from gen.fuzzlang_dsl.observed_retarget import select_observed_retargets


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _covered_names(paths: Iterable[Path]) -> set[str]:
    names: set[str] = set()
    for path in paths:
        value = json.loads(path.read_text())
        if value.get("schema") != "fuzzlang.verified_injector_coverage_audit.v1":
            raise ValueError(f"unsupported strict coverage audit: {path}")
        entries = value.get("verified_diagnostic_names")
        if not isinstance(entries, list) or any(
            not isinstance(name, str) or not name for name in entries
        ):
            raise ValueError(f"invalid verified diagnostic names: {path}")
        names.update(entries)
    return names


def _write_jsonl(path: Path, values: Iterable[dict[str, Any]]) -> int:
    payload = "".join(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
        for value in values
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload)
    return payload.count("\n")


def _file_info(path: Path, *, rows: int | None = None) -> dict[str, Any]:
    payload = path.read_bytes()
    result: dict[str, Any] = {
        "path": str(path),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    if rows is not None:
        result["rows"] = rows
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--injectors", type=Path, required=True)
    parser.add_argument("--rejections", type=Path, action="append", required=True)
    parser.add_argument("--catalog-dir", required=True)
    parser.add_argument("--covered-audit", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--manifest-out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.resolve() == args.manifest_out.resolve():
        raise ValueError("out and manifest-out must be distinct")
    injectors = load_injectors_jsonl(args.injectors)
    rejection_rows = [row for path in args.rejections for row in _rows(path)]
    catalog = load_catalog(args.catalog_dir)
    selected, summary = select_observed_retargets(
        injectors,
        rejection_rows,
        catalog_error_names={entry.name for entry in catalog.errors()},
        covered_names=_covered_names(args.covered_audit),
    )
    row_count = _write_jsonl(args.out, (item.to_dict() for item in selected))
    manifest = {
        "schema": "fuzzlang.observed_diagnostic_retarget.v1",
        "uses_llm_api": False,
        "selection": summary,
        "inputs": {
            "injectors": _file_info(args.injectors, rows=len(injectors)),
            "rejections": [_file_info(path, rows=len(_rows(path))) for path in args.rejections],
            "covered_audits": [_file_info(path) for path in args.covered_audit],
        },
        "output": _file_info(args.out, rows=row_count),
    }
    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_out.write_text(json.dumps(manifest, sort_keys=True) + "\n")
    print(f"[observed-retarget] injectors={row_count} uses_llm_api=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
