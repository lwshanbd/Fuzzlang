#!/usr/bin/env python3
"""Freeze the train/eval split of every clean source pool before generation.

This must run *before* any E1 generation. It writes one split-labelled source
file per pool plus a manifest, so every later run can refuse to emit a training
record from a held-out translation unit or a held-out project.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from gen.realcorpus.source_splits import (
    SplitPolicy, assign_source_splits, split_manifest,
)


def _load_pool(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text().splitlines() if line.strip()
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pool", type=Path, action="append", required=True,
        help="clean source pool sources.jsonl; repeatable",
    )
    parser.add_argument(
        "--held-out-project", action="append", default=[],
        help="project excluded from training entirely; repeatable",
    )
    parser.add_argument("--eval-fraction", type=float, default=0.15)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument(
        "--out-dir", type=Path, required=True,
        help="directory receiving one split-labelled JSONL per pool",
    )
    parser.add_argument("--manifest-out", type=Path, required=True)
    args = parser.parse_args()

    policy = SplitPolicy(
        seed=args.seed,
        held_out_projects=tuple(sorted(set(args.held_out_project))),
        eval_fraction=args.eval_fraction,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict] = []
    inputs: list[dict] = []
    seen_ids: set[str] = set()
    for pool in args.pool:
        payload = pool.read_bytes()
        rows = _load_pool(pool)
        assigned = assign_source_splits(rows, policy)
        duplicates = sorted(
            {row["source_id"] for row in assigned} & seen_ids
        )
        if duplicates:
            raise SystemExit(
                f"{pool}: {len(duplicates)} source ids already appear in an "
                f"earlier pool, e.g. {duplicates[:3]}"
            )
        seen_ids.update(row["source_id"] for row in assigned)

        out = args.out_dir / f"{pool.parent.name}.sources.split.jsonl"
        out.write_text("".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in assigned
        ))
        all_rows.extend(assigned)
        inputs.append({
            "pool": str(pool),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "sources": len(rows),
            "out": str(out),
        })

    manifest = split_manifest(all_rows, policy)
    manifest["inputs"] = inputs
    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "policy": manifest["policy"],
        "totals": manifest["totals"],
        "counts": manifest["counts"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
