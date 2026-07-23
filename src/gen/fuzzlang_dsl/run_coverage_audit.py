#!/usr/bin/env python3
"""Audit strict typed-diagnostic coverage backed by portable Injectors."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gen.fuzzlang_dsl.coverage_audit import (
    audit_verified_injector_coverage,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--injectors", type=Path, action="append", required=True)
    parser.add_argument("--records", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = audit_verified_injector_coverage(
        args.injectors, args.records,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered)
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
