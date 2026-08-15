#!/usr/bin/env python3
"""Freeze the stratified E1 diagnostic sample from the canonical inventory."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from gen.fuzzlang_dsl.e1_targets import select_e1_targets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--diagnostic-record-map", type=Path, required=True,
        help="diagnostic_record_map.csv from the canonical strict audit",
    )
    parser.add_argument("--size", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--language", default="c++")
    parser.add_argument("--names-out", type=Path, required=True)
    parser.add_argument("--manifest-out", type=Path, required=True)
    args = parser.parse_args()

    source = args.diagnostic_record_map.read_bytes()
    rows = list(csv.DictReader(args.diagnostic_record_map.read_text().splitlines()))
    targets = select_e1_targets(
        rows, seed=args.seed, size=args.size, language=args.language,
    )

    args.names_out.parent.mkdir(parents=True, exist_ok=True)
    args.names_out.write_text(
        "".join(target.diag_name + "\n" for target in targets)
    )
    strata: dict[str, int] = {}
    for target in targets:
        strata[target.stratum] = strata.get(target.stratum, 0) + 1
    args.manifest_out.write_text(json.dumps({
        "schema": "fuzzlang.e1_target_sample.v1",
        "selection_rule": (
            "canonical strict audit rows filtered to in_paper_scope=true, "
            "language present, and at least one strictly verified record; "
            "stratified evenly over catalog component (error family) then over "
            "existing-multiplicity band (1 / 2-3 / 4+); drawn with "
            "random.Random(seed) after sorting each stratum by diagnostic name"
        ),
        "seed": args.seed,
        "size": len(targets),
        "language": args.language,
        "inventory": {
            "path": str(args.diagnostic_record_map),
            "sha256": hashlib.sha256(source).hexdigest(),
            "eligible_rows": sum(
                1 for row in rows
                if row.get("in_paper_scope") == "true"
                and args.language in row.get("languages", "").split("|")
            ),
        },
        "strata": dict(sorted(strata.items())),
        "targets": [target.to_dict() for target in targets],
    }, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "size": len(targets), "seed": args.seed,
        "strata": dict(sorted(strata.items())),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
