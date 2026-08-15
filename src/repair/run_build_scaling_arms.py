#!/usr/bin/env python3
"""Build nested FuzzLang training arms for a data-scaling curve.

E3 matched every arm to 557 records -- the size the most expensive arm
(DirectEdit, one model call per record) could reach. FuzzLang can supply an
order of magnitude more at no additional cost, so the matched comparison is a
lower bound on what its data is worth. This builds the same arm at several
sizes, under the identical leakage guard and rendering, so the curve answers
one question: does more FuzzLang data keep helping?

The tiers are nested (see ``select_scaling_tiers``), so a difference between
them is quantity and not composition.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from repair.build_sft_arms import (
    build_eval_guard,
    select_by_breadth,
    load_injector_map,
    load_stable_diag_ids,
    prepare_candidates,
    select_scaling_tiers,
    _write_rows,
)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fuzzlang", action="append", required=True)
    parser.add_argument("--fuzzlang-recipes", action="append", default=[])
    parser.add_argument("--injector-library", action="append", default=[])
    parser.add_argument("--eval", action="append", required=True)
    parser.add_argument("--diag-evidence", action="append", default=[])
    parser.add_argument("--tokenizer", required=True)
    parser.add_argument("--model-revision")
    parser.add_argument("--sizes",
                        help="Comma-separated record counts, e.g. 557,1500,5000")
    parser.add_argument(
        "--breadth", choices=("broad", "narrow"),
        help=(
            "Instead of nested size tiers, build one arm of --count records "
            "whose diagnostic coverage is as wide (broad) or as concentrated "
            "(narrow) as the pool allows. Pairing a broad and a narrow arm at "
            "the same count separates 'more data' from 'more diverse data'."
        ),
    )
    parser.add_argument("--count", type=int)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-seq-len", type=int, default=1024)
    parser.add_argument("--on-overlength", choices=("error", "exclude"),
                        default="exclude")
    parser.add_argument("--context-lines", type=int, default=8)
    parser.add_argument("--max-window-chars", type=int, default=8_000)
    parser.add_argument("--max-edit-chars", type=int, default=2_000)
    parser.add_argument("--local-files-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if bool(args.breadth) == bool(args.sizes):
        raise SystemExit("pass exactly one of --sizes or --breadth")
    if args.breadth and not args.count:
        raise SystemExit("--breadth requires --count")
    sizes = (
        [int(part) for part in args.sizes.split(",") if part.strip()]
        if args.sizes else []
    )

    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        args.tokenizer, revision=args.model_revision,
        local_files_only=args.local_files_only,
    )

    diag_ids, _ = (
        load_stable_diag_ids(args.diag_evidence) if args.diag_evidence else ({}, None)
    )
    injector_map, _ = load_injector_map(args.fuzzlang_recipes, diag_ids=diag_ids)
    injector_by_id = {}
    if args.injector_library:
        from gen.fuzzlang_dsl.library_replay import load_injector_library

        injector_by_id = {
            injector.injector_id: injector
            for injector in load_injector_library(
                [Path(p) for p in args.injector_library]
            )
        }

    eval_guard, eval_report = build_eval_guard(
        args.eval,
        context_lines=args.context_lines,
        max_window_chars=args.max_window_chars,
        max_edit_chars=args.max_edit_chars,
    )
    candidates, exclusions = prepare_candidates(
        "fuzzlang", args.fuzzlang,
        tokenizer=tokenizer, eval_guard=eval_guard,
        injector_by_recipe=injector_map, injector_by_id=injector_by_id,
        max_seq_len=args.max_seq_len, on_overlength=args.on_overlength,
        context_lines=args.context_lines,
        max_window_chars=args.max_window_chars,
        max_edit_chars=args.max_edit_chars,
    )

    if args.breadth:
        tiers = {
            args.count: select_by_breadth(
                candidates, count=args.count, mode=args.breadth, seed=args.seed,
            )
        }
    else:
        tiers = select_scaling_tiers(candidates, sizes=sizes, seed=args.seed)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    tier_report = {}
    previous: set[str] = set()
    for size in sorted(tiers):
        selected = tiers[size]
        label = f"{args.breadth}-{size}" if args.breadth else str(size)
        stats = _write_rows(out / f"fuzzlang-{label}.train.jsonl",
                            [candidate.row for candidate in selected])
        ids = {candidate.record_id for candidate in selected}
        tier_report[str(size)] = {
            "records": len(selected),
            "rendered_tokens": sum(c.rendered_tokens for c in selected),
            "distinct_diagnostics": len({c.diagnostic for c in selected}),
            "distinct_sources": len({c.source_key for c in selected}),
            # Proof the curve isolates quantity: each tier contains the last.
            "contains_previous_tier": previous <= ids,
            **{k: v for k, v in stats.items() if k != "path"},
        }
        previous = ids

    manifest = {
        "schema": "fuzzlang.scaling_arms.v1",
        "arm": "fuzzlang",
        "seed": args.seed,
        "sizes": sizes,
        "breadth": args.breadth,
        "eligible_pool": len(candidates),
        "exclusions": dict(sorted(exclusions.items())),
        "eval_guard": eval_report,
        "tokenizer": args.tokenizer,
        "model_revision": args.model_revision,
        "max_seq_len": args.max_seq_len,
        "on_overlength": args.on_overlength,
        "tiers": tier_report,
        "inputs": {
            "fuzzlang": list(args.fuzzlang),
            "eval": list(args.eval),
            "injector_library": list(args.injector_library),
        },
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(
        {"eligible_pool": len(candidates), "tiers": tier_report}, indent=2,
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
