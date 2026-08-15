#!/usr/bin/env python3
"""Split synthesized Injectors by the compiler mode of their source request.

The mode is prompt provenance, not a property inferred from the model output.
Keeping this mapping lets later replay clean-gate real production TUs under the
same language mode that the matching Clang regression test required.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Sequence


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _filename_label(mode: str) -> str:
    return mode.replace("+", "x").replace("/", "_")


def split_injectors_by_mode(
    *, requests: Sequence[dict[str, Any]], injectors: Sequence[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Map Injector rows to their request's explicit replay mode."""
    mode_by_target: dict[str, str] = {}
    for request in requests:
        name = request.get("diag_name")
        mode = request.get("fuzzlang_mode_label")
        if not isinstance(name, str) or not name:
            raise ValueError("mode request lacks diag_name")
        if not isinstance(mode, str) or not mode:
            raise ValueError(f"mode request {name} lacks fuzzlang_mode_label")
        previous = mode_by_target.setdefault(name, mode)
        if previous != mode:
            raise ValueError(f"target {name} maps to conflicting modes")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for injector in injectors:
        target = injector.get("target")
        name = target.get("diag_name") if isinstance(target, dict) else None
        if not isinstance(name, str) or name not in mode_by_target:
            raise ValueError(f"Injector target {name!r} has no mode request")
        grouped[mode_by_target[name]].append(injector)
    return {mode: grouped[mode] for mode in sorted(grouped)}


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.write_text("".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
    ))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--injectors", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--manifest-out", type=Path, required=True)
    args = parser.parse_args()
    grouped = split_injectors_by_mode(
        requests=_load_jsonl(args.requests), injectors=_load_jsonl(args.injectors),
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    groups: list[dict[str, Any]] = []
    for mode, rows in grouped.items():
        output = args.out_dir / f"injectors-{_filename_label(mode)}.jsonl"
        _write_jsonl(output, rows)
        groups.append({
            "mode": mode,
            "injectors": len(rows),
            "targets": len({row["target"]["diag_name"] for row in rows}),
            "path": str(output),
        })
    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_out.write_text(json.dumps({
        "schema": "fuzzlang.mode_injector_split",
        "schema_version": 1,
        "inputs": {"requests": str(args.requests), "injectors": str(args.injectors)},
        "groups": groups,
    }, sort_keys=True) + "\n")
    print(json.dumps({"modes": len(groups), "injectors": sum(item["injectors"] for item in groups)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
