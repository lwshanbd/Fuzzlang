#!/usr/bin/env python3
"""Target-first real-code error injection driver.

For each in-scope target diagnostic (covered-first), pick feature-relevant real
fragments, ask the model for a minimal edit that triggers the target, verify
with the real compile command, and emit run_sweep-format rows. Bounded by
--max-instances (the first eval slice = the highest-yield prefix of the
catalog).

    PYTHONPATH=src /usr/tce/bin/python3 src/gen/realcorpus/run_realcorpus.py \
      --compile-db /p/lustre2/shan4/fuzzlang-llvm-build/compile_commands.json \
      --clang-bin $FUZZLANG_CLANG_BIN --diagtool-bin $FUZZLANG_DIAGTOOL_BIN \
      --dataset data/gen/splits/train.jsonl \
      --out-of-scope data/gen/out_of_scope.txt \
      --model gpt-5.4-mini --base-url https://api.openai.com/v1 \
      --n-files 300 --candidates-per-target 4 --max-instances 300 \
      --out data/gen/splits/eval_realcorpus.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Callable

from foundation.compile_db import load_compile_db
from foundation.diagnostics.catalog import load_catalog
from foundation.record import Record, Split
from foundation.verifier import FuzzlangClangVerifier
from gen.realcorpus.collect import collect_real_record
from gen.realcorpus.corpus import Fragment, build_fragment_index
from gen.realcorpus.inject import inject_target
from gen.realcorpus.select import rank_fragments
from gen.realcorpus.targets import Target, build_targets, load_exemplars


def drive_targets(
    targets: list[Target],
    fragments: list[Fragment],
    verifier,
    *,
    chat,
    inject_fn: Callable = inject_target,
    candidates_per_target: int,
    max_instances: int,
    split: Split = Split.EVAL,
) -> list[Record]:
    """Core orchestration: one emitted Record per target that injects+verifies,
    up to max_instances. `inject_fn` is injectable for testing."""
    out: list[Record] = []
    for target in targets:
        if len(out) >= max_instances:
            break
        for frag in rank_fragments(target, fragments, k=candidates_per_target):
            erroneous = inject_fn(target, frag, chat)
            if erroneous is None:
                continue
            lang = "c" if frag.rel_path.endswith(".c") else "c++"
            rec = collect_real_record(frag, erroneous, target, verifier,
                                      split=split, language=lang)
            if rec is not None:
                out.append(rec)
                break  # one instance per target; move on
    return out


def to_run_sweep_row(rec: Record, fragment: Fragment) -> dict:
    d = rec.primary_diagnostic
    det = rec.provenance.detail
    return {
        "instance_id": rec.record_id,
        "buggy_src": rec.erroneous_src,
        "corrected_src": rec.corrected_src,
        "compile_cmd": fragment.compile_cmd,
        "diag_id": d.diag_id if d else None,
        "diag_name": d.diag_name if d else None,
        "language": rec.language,
        "cascade_size": det.get("cascade_size"),
        "target_diag": det.get("target_diag"),
        "primary_matches_target": det.get("primary_matches_target"),
    }


def _chat_fn(model: str, base_url: str):
    from repair.agent.chat_backend import OpenAIChatBackend
    backend = OpenAIChatBackend(model, base_url=base_url,
                               api_key=os.environ.get("OPENAI_API_KEY", "EMPTY"))

    def chat(messages, temperature: float) -> str:
        r = backend.chat(messages=messages, temperature=temperature,
                         max_tokens=512, n=1)
        return r[0].text if r else ""
    return chat


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--compile-db", type=Path, required=True)
    ap.add_argument("--clang-bin", required=True)
    ap.add_argument("--diagtool-bin", required=True)
    ap.add_argument("--dataset", type=Path, required=True, help="exemplar source JSONL")
    ap.add_argument("--out-of-scope", type=Path, required=True)
    ap.add_argument("--model", default="gpt-5.4-mini")
    ap.add_argument("--base-url", default="https://api.openai.com/v1")
    ap.add_argument("--n-files", type=int, default=300)
    ap.add_argument("--candidates-per-target", type=int, default=4)
    ap.add_argument("--max-instances", type=int, default=300)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    verifier = FuzzlangClangVerifier(clang_bin=args.clang_bin,
                                     diagtool_bin=args.diagtool_bin, timeout_s=30.0)
    db = load_compile_db(args.compile_db)
    print(f"[realcorpus] compile db: {len(db)} TUs", flush=True)
    frags = build_fragment_index(db, verifier, n_files=args.n_files, seed=args.seed)
    print(f"[realcorpus] fragment pool: {len(frags)} fragments", flush=True)

    out_of_scope = {l.strip() for l in args.out_of_scope.read_text().splitlines()
                    if l.strip()}
    exemplars = load_exemplars(args.dataset)
    targets = build_targets(load_catalog().errors(), out_of_scope, exemplars)
    print(f"[realcorpus] targets: {len(targets)} in-scope "
          f"({sum(t.covered for t in targets)} covered-first)", flush=True)

    chat = _chat_fn(args.model, args.base_url)

    # main() inlines the drive loop (vs. calling drive_targets) so it can stream
    # progress and rows; drive_targets stays the unit-tested pure core.
    records: list[Record] = []
    rows: list[dict] = []
    remaining = args.max_instances
    for target in targets:
        if remaining <= 0:
            break
        for frag in rank_fragments(target, frags, k=args.candidates_per_target):
            erroneous = inject_target(target, frag, chat)
            if erroneous is None:
                continue
            lang = "c" if frag.rel_path.endswith(".c") else "c++"
            rec = collect_real_record(frag, erroneous, target, verifier, language=lang)
            if rec is not None:
                records.append(rec)
                rows.append(to_run_sweep_row(rec, frag))
                remaining -= 1
                print(f"[realcorpus] {len(rows)}/{args.max_instances} "
                      f"{target.name} match={rec.provenance.detail['primary_matches_target']} "
                      f"cascade={rec.provenance.detail['cascade_size']}", flush=True)
                break

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    matched = sum(1 for r in rows if r["primary_matches_target"])
    print(f"[realcorpus] DONE wrote {len(rows)} rows -> {args.out} "
          f"({matched} primary==target)", flush=True)


if __name__ == "__main__":
    main()
