#!/usr/bin/env python3
"""CLI for the read-only Breadth/RealSource/NatErr release audit."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from gen.data_audit import audit_tiers


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Stream and audit the three frozen FuzzLang data tiers."
    )
    parser.add_argument("--breadth", type=Path, action="append", required=True)
    parser.add_argument(
        "--real-source", type=Path, action="append", required=True,
        help="canonical errors injected into non-test real-project source",
    )
    parser.add_argument("--naterr", type=Path, action="append", required=True)
    parser.add_argument(
        "--out", type=Path,
        help="optional JSON report path; the same report is always printed",
    )
    args = parser.parse_args(argv)

    report = audit_tiers(
        {
            "breadth": args.breadth,
            "real_source": args.real_source,
            "naterr": args.naterr,
        }
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
