#!/usr/bin/env python3
"""Emit the NatErr build-snapshot plan, and the candidate slice for one snapshot.

Two modes:

* ``--plan-out`` writes the ordered snapshot list (densest cluster first), so a
  campaign that is cut short after k builds has spent those k well.
* ``--snapshot-date`` writes just the candidates one build can serve, which is
  what the campaign driver feeds to Stage 2.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from real.naterr_snapshots import candidates_in_window, select_snapshots


def _load(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text().splitlines() if line.strip()
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--window-days", type=int, default=21)
    parser.add_argument("--max-snapshots", type=int)
    parser.add_argument("--plan-out", type=Path)
    parser.add_argument(
        "--snapshot-date",
        help="Emit the candidates one build at this date can serve.",
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    candidates = _load(args.manifest)

    if args.snapshot_date:
        if args.out is None:
            parser.error("--snapshot-date requires --out")
        slice_ = candidates_in_window(
            candidates, args.snapshot_date, window_days=args.window_days
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in slice_)
        )
        print(f"{len(slice_)} candidates within "
              f"+/-{args.window_days}d of {args.snapshot_date}")
        return 0

    plan = select_snapshots(
        candidates,
        window_days=args.window_days,
        max_snapshots=args.max_snapshots,
    )
    payload = {
        "schema": "fuzzlang.naterr_snapshot_plan.v1",
        "manifest": str(args.manifest),
        "candidates": len(candidates),
        "window_days": args.window_days,
        "snapshots": plan,
        "cumulative_coverage": [
            sum(entry["covers"] for entry in plan[: n + 1])
            for n in range(len(plan))
        ],
    }
    rendered = json.dumps(payload, indent=2) + "\n"
    if args.plan_out is not None:
        args.plan_out.parent.mkdir(parents=True, exist_ok=True)
        args.plan_out.write_text(rendered)
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
