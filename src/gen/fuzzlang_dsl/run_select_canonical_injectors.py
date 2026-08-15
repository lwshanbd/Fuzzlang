#!/usr/bin/env python3
"""Select a compact canonical Injector library from campaign evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gen.fuzzlang_dsl.campaign import load_injectors_jsonl
from gen.fuzzlang_dsl.injector_selection import select_canonical_injectors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--injectors", type=Path, required=True)
    parser.add_argument("--campaign-manifest", type=Path, action="append", required=True)
    parser.add_argument("--selected-out", type=Path, required=True)
    parser.add_argument("--report-out", type=Path, required=True)
    parser.add_argument("--min-exact-target", type=int, default=1)
    parser.add_argument("--min-unique-tus", type=int, default=1)
    parser.add_argument("--min-target-rate", type=float, default=0.0)
    parser.add_argument("--backups-per-diagnostic", type=int, default=1)
    args = parser.parse_args()
    input_paths = {args.injectors.resolve(), *(path.resolve() for path in args.campaign_manifest)}
    if args.selected_out.resolve() in input_paths:
        raise ValueError("--selected-out must not overwrite an input")
    if args.report_out.resolve() in input_paths | {args.selected_out.resolve()}:
        raise ValueError("--report-out must be distinct from inputs and selected output")

    injectors = load_injectors_jsonl(args.injectors)
    manifests = [json.loads(path.read_text()) for path in args.campaign_manifest]
    report = select_canonical_injectors(
        injectors, manifests,
        min_exact_target=args.min_exact_target,
        min_unique_tus=args.min_unique_tus,
        min_target_rate=args.min_target_rate,
        backups_per_diagnostic=args.backups_per_diagnostic,
    )
    selected = set(report["selected_injector_ids"])
    args.selected_out.parent.mkdir(parents=True, exist_ok=True)
    args.selected_out.write_text("".join(
        injector.to_json() + "\n" for injector in injectors
        if injector.injector_id in selected
    ))
    args.report_out.parent.mkdir(parents=True, exist_ok=True)
    args.report_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    counts = report["counts"]
    print(
        "[select-canonical-injectors] "
        f"primary={counts['primary']} backup={counts['backup']} "
        f"rejected={counts['rejected']}"
    )
    return 0
