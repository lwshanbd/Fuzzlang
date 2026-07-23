#!/usr/bin/env python3
"""Build a reusable diagnostic-to-emission-site index from Clang source."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gen.fuzzlang_dsl.emission_evidence import (
    build_emission_index,
    write_emission_index,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clang-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--context-lines", type=int, default=2)
    parser.add_argument("--max-sites-per-diagnostic", type=int, default=2)
    args = parser.parse_args()
    try:
        index = build_emission_index(
            args.clang_root,
            context_lines=args.context_lines,
            max_sites_per_diagnostic=args.max_sites_per_diagnostic,
        )
    except ValueError as error:
        parser.error(str(error))
    write_emission_index(args.out, index)
    print(json.dumps({
        "diagnostic_types": len(index),
        "emission_sites": sum(len(sites) for sites in index.values()),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
