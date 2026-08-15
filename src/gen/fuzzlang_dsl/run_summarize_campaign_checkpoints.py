#!/usr/bin/env python3
"""Write a replay-compatible partial manifest from durable campaign checkpoints."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from gen.fuzzlang_dsl.checkpoint_summary import summarize_checkpoint_campaign
from gen.fuzzlang_dsl.retry import load_json_rows


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--injectors", type=Path, required=True)
    parser.add_argument("--rejections", type=Path, action="append", required=True)
    parser.add_argument("--records", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.out.resolve() in {
        args.injectors.resolve(),
        *(path.resolve() for path in args.rejections),
        *(path.resolve() for path in args.records),
    }:
        raise ValueError("output must not overwrite a checkpoint input")
    injectors = load_json_rows(args.injectors)
    rejections = [row for path in args.rejections for row in load_json_rows(path)]
    records = [row for path in args.records for row in load_json_rows(path)]
    metrics = summarize_checkpoint_campaign(injectors, rejections, records)
    payload: dict[str, Any] = {
        "schema": "fuzzlang.synthesized_injector_campaign_checkpoint.v1",
        "complete": False,
        "injectors": metrics,
        "checkpoint_counts": {
            "injectors_with_candidate_outcomes": len(metrics),
            "rejections": len(rejections),
            "records": len(records),
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, sort_keys=True) + "\n")
    print(f"[checkpoint-summary] injectors={len(metrics)} records={len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
