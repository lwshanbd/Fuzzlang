#!/usr/bin/env python3
"""P009 dedup audit: pairwise AST-hash collision check between manifests.

Implements gate G-M2's hard half:
  "AST-hash dedup audit passes on X-train ↔ X-dev AND X ↔ Y"

Usage:
  PYTHONPATH=. python scripts/run_p009_dedup_audit.py \\
      --train data/splits/x_train_mutations.jsonl \\
      --dev   data/splits/x_dev_mutations.jsonl \\
      --eval  data/natErr/y_eval_mutations.jsonl \\
      --hash-mode ast \\
      --report-out data/splits/p009_dedup_audit.json

Each input JSONL row must have at minimum:
  {"file_path": "...", "line": <int>,
   "mutated_src": "<full file content>"}    OR
  {"file_path": "...", "line": <int>,
   "snippet": "<5-line window text>"}

If `mutated_src` is present, we recompute the 5-line window from line.
If only `snippet` is present, we hash that directly.

The audit is GREEN iff:
  - X-train ↔ X-dev: zero collisions (sanity, since file-level carve
    already guarantees disjoint files; this catches accidental crossover)
  - X-train ↔ Y-eval: zero collisions (the load-bearing constraint —
    if any Y eval instance has the same hash as a training mutation,
    we reject it BEFORE running Column A).

Exit code 0 = green. Non-zero = red (unless --no-fail-on-collision).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

from experiments.fuzzlang_transformer.ast_hash import (
    text_normalized_hash, ast_normalized_hash, five_line_window,
)


def _load_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open() as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            rows.append(json.loads(ln))
    return rows


def _row_hash(row: dict, mode: str) -> str:
    if "snippet" in row:
        snippet = row["snippet"]
    elif "mutated_src" in row:
        snippet = five_line_window(row["mutated_src"], int(row["line"]))
    elif "buggy_src" in row:                    # NatErr-shaped row
        snippet = five_line_window(row["buggy_src"], int(row["line"]))
    else:
        raise KeyError(
            f"row needs `snippet` or `mutated_src` or `buggy_src`: "
            f"{set(row.keys())}"
        )
    if mode == "text":
        return text_normalized_hash(snippet, line=3)  # hash the snippet directly
    elif mode == "ast":
        # `snippet` is already 5 lines; ast_hash takes (src, line) so re-pass
        # the snippet as src and use middle line.
        line_in_snippet = min(3, len(snippet.splitlines()))
        return ast_normalized_hash(snippet, line=line_in_snippet)
    else:
        raise ValueError(f"unknown hash mode: {mode}")


def _hash_index(rows: list[dict], mode: str) -> dict[str, list[int]]:
    """Hash-keyed index from row indices."""
    idx: dict[str, list[int]] = {}
    for i, r in enumerate(rows):
        try:
            h = _row_hash(r, mode)
        except KeyError as e:
            print(f"[dedup] row {i} skipped: {e}", file=sys.stderr)
            continue
        idx.setdefault(h, []).append(i)
    return idx


def _pairwise(name_a: str, idx_a: dict[str, list[int]],
              name_b: str, idx_b: dict[str, list[int]]) -> dict:
    shared = set(idx_a) & set(idx_b)
    return {
        "left": name_a,
        "right": name_b,
        "left_unique_hashes": len(idx_a),
        "right_unique_hashes": len(idx_b),
        "collisions": len(shared),
        "ok": len(shared) == 0,
        "examples": sorted(shared)[:5],
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--train", type=Path, required=True,
                   help="X-train mutation manifest JSONL")
    p.add_argument("--dev", type=Path, default=None,
                   help="X-dev mutation manifest JSONL (optional)")
    p.add_argument("--eval", type=Path, default=None,
                   help="Y-eval mutation manifest JSONL (optional)")
    p.add_argument("--hash-mode", choices=["text", "ast"], default="ast")
    p.add_argument("--report-out", type=Path, required=True)
    p.add_argument("--no-fail-on-collision", action="store_true",
                   help="Don't exit non-zero on collision (still write report).")
    args = p.parse_args()

    train_rows = _load_rows(args.train)
    dev_rows = _load_rows(args.dev) if args.dev else []
    eval_rows = _load_rows(args.eval) if args.eval else []

    print(f"[dedup] train={len(train_rows)}  dev={len(dev_rows)}  "
          f"eval={len(eval_rows)}  hash={args.hash_mode}", flush=True)

    train_idx = _hash_index(train_rows, args.hash_mode)
    dev_idx = _hash_index(dev_rows, args.hash_mode) if dev_rows else {}
    eval_idx = _hash_index(eval_rows, args.hash_mode) if eval_rows else {}

    pairs = []
    if dev_idx:
        pairs.append(_pairwise("train", train_idx, "dev", dev_idx))
    if eval_idx:
        pairs.append(_pairwise("train", train_idx, "eval", eval_idx))
    if dev_idx and eval_idx:
        pairs.append(_pairwise("dev", dev_idx, "eval", eval_idx))

    overall_ok = all(p["ok"] for p in pairs)
    report = {
        "schema_version": 1,
        "task": "P009 dedup audit (G-M2 second half)",
        "hash_mode": args.hash_mode,
        "inputs": {
            "train": str(args.train),
            "dev": str(args.dev) if args.dev else None,
            "eval": str(args.eval) if args.eval else None,
        },
        "row_counts": {
            "train": len(train_rows),
            "dev": len(dev_rows),
            "eval": len(eval_rows),
        },
        "unique_hash_counts": {
            "train": len(train_idx),
            "dev": len(dev_idx),
            "eval": len(eval_idx),
        },
        "pairs": pairs,
        "overall_ok": overall_ok,
    }

    args.report_out.parent.mkdir(parents=True, exist_ok=True)
    args.report_out.write_text(json.dumps(report, indent=2, sort_keys=True))
    print(f"[dedup] report -> {args.report_out}", flush=True)
    for p_ in pairs:
        flag = "OK" if p_["ok"] else f"COLLISIONS={p_['collisions']}"
        print(f"  {p_['left']:>10s} <-> {p_['right']:<10s}  "
              f"left_uniq={p_['left_unique_hashes']:>6d}  "
              f"right_uniq={p_['right_unique_hashes']:>6d}  {flag}")
    print(f"[dedup] overall: {'GREEN' if overall_ok else 'RED'}", flush=True)
    if not overall_ok and not args.no_fail_on_collision:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
