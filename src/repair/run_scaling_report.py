#!/usr/bin/env python3
"""Emit the E5 data-scaling curve as JSON and CSV."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Sequence

from repair.scaling_report import build_scaling_report, scaling_rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20260813)
    args = parser.parse_args(argv)

    report = build_scaling_report(
        args.eval_dir, bootstrap_samples=args.bootstrap_samples, seed=args.seed,
    )
    report["inputs"] = {"eval_dir": args.eval_dir}

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "scaling-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    rows = scaling_rows(report)
    with (out / "scaling_curve.csv").open("w", newline="") as stream:
        csv.writer(stream).writerows(rows)
    for row in rows:
        print("  ".join("" if cell is None else str(cell) for cell in row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
