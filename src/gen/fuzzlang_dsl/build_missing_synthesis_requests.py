#!/usr/bin/env python3
"""Emit synthesis requests whose target diagnostics lack an Injector artifact."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, Sequence


def _rows(path: Path) -> Iterable[dict]:
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{number}: expected object")
        yield value


def missing_requests(requests: Path, injector_paths: Sequence[Path]) -> list[dict]:
    """Keep request rows not represented by an Injector target name."""
    covered: set[str] = set()
    for path in injector_paths:
        for row in _rows(path):
            try:
                covered.add(row["target"]["diag_name"])
            except (KeyError, TypeError) as error:
                raise ValueError(f"{path}: invalid Injector row") from error
    selected: list[dict] = []
    seen: set[str] = set()
    for row in _rows(requests):
        name = row.get("diag_name")
        if not isinstance(name, str):
            raise ValueError(f"{requests}: request lacks diag_name")
        if name not in covered and name not in seen:
            selected.append(row)
            seen.add(name)
    return selected


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--injectors-glob", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    paths = sorted(args.requests.parent.glob(args.injectors_glob))
    if not paths:
        raise ValueError("--injectors-glob matched no artifacts")
    selected = missing_requests(args.requests, paths)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in selected))
    print(f"[build-missing-synthesis-requests] requests={len(selected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
