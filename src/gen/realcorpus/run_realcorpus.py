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
from gen.realcorpus.induce import induce_target
from gen.realcorpus.ranking import rank_fragments
from gen.realcorpus.targets import Target, build_targets, load_exemplars


def drive_targets(
    targets: list[Target],
    fragments: list[Fragment],
    verifier,
    *,
    chat,
    induce_fn: Callable = induce_target,
    candidates_per_target: int,
    max_instances: int,
    split: Split = Split.EVAL,
    workers: int = 1,
    max_attempts: int = 3,
    temperature: float = 0.8,
    on_emit=None,
) -> list[Record]:
    """Core orchestration: one emitted Record per target that injects+verifies,
    up to max_instances (covered-first priority preserved by processing targets
    in order). Parallelized across targets with a thread pool. `induce_fn` is
    injectable for testing; `on_emit(rec, frag)` is called for each kept record."""
    from concurrent.futures import ThreadPoolExecutor

    def work(target):
        for frag in rank_fragments(target, fragments, k=candidates_per_target):
            induced = induce_fn(target, frag, chat, verifier,
                                max_attempts=max_attempts, temperature=temperature)
            if induced is None:
                continue
            erroneous, res = induced
            lang = "c" if frag.rel_path.endswith(".c") else "c++"
            rec = collect_real_record(frag, erroneous, target, verifier,
                                      split=split, language=lang, result=res)
            if rec is not None:
                return rec, frag
        return None

    out: list[Record] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        i = 0
        block = max(1, workers) * 4
        while i < len(targets) and len(out) < max_instances:
            chunk = targets[i:i + block]
            i += len(chunk)
            for res in ex.map(work, chunk):
                if res is None:
                    continue
                rec, frag = res
                out.append(rec)
                if on_emit is not None:
                    on_emit(rec, frag)
                if len(out) >= max_instances:
                    break
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
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--temperature", type=float, default=0.8)
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

    rows: list[dict] = []

    def on_emit(rec, frag):
        rows.append(to_run_sweep_row(rec, frag))
        det = rec.provenance.detail
        print(f"[realcorpus] {len(rows)}/{args.max_instances} {det['target_diag']} "
              f"match={det['primary_matches_target']} cascade={det['cascade_size']}",
              flush=True)

    drive_targets(
        targets, frags, verifier, chat=chat,
        candidates_per_target=args.candidates_per_target,
        max_instances=args.max_instances, workers=args.workers,
        max_attempts=args.max_attempts, temperature=args.temperature, on_emit=on_emit,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    matched = sum(1 for r in rows if r["primary_matches_target"])
    print(f"[realcorpus] DONE wrote {len(rows)} rows -> {args.out} "
          f"({matched} primary==target)", flush=True)


if __name__ == "__main__":
    main()
