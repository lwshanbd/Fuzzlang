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
import threading
from collections import Counter
from pathlib import Path
from typing import Callable

from foundation.compile_db import load_compile_db
from coverage.tracker import INVOCATION_COMPONENTS
from foundation.diagnostics.catalog import load_catalog
from foundation.record import Record, Split
from foundation.verifier import FuzzlangClangVerifier
from gen.realcorpus.collect import collect_real_record
from gen.realcorpus.corpus import Fragment, build_fragment_index, is_test_path
from gen.realcorpus.induce import induce_target
from gen.realcorpus.ranking import rank_fragments
from gen.realcorpus.targets import (Target, build_targets, load_exemplars,
                                    load_observed_names,
                                    load_diagnostic_languages)


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
    on_attempt=None,
    on_near_miss=None,
    max_instances_per_source: int = 0,
    project: str = "llvm",
) -> list[Record]:
    """Core orchestration: one emitted Record per target that injects+verifies,
    up to max_instances (covered-first priority preserved by processing targets
    in order). Parallelized across targets with a thread pool. `induce_fn` is
    injectable for testing; `on_emit(rec, frag)` is called for each kept record."""
    from concurrent.futures import ThreadPoolExecutor

    def work(target, excluded_sources=frozenset()):
        for frag in rank_fragments(target, fragments, k=candidates_per_target):
            if frag.rel_path in excluded_sources:
                continue
            induced = induce_fn(target, frag, chat, verifier,
                                max_attempts=max_attempts, temperature=temperature,
                                on_attempt=on_attempt, on_near_miss=on_near_miss)
            if induced is None:
                continue
            erroneous, res = induced
            lang = "c" if frag.rel_path.endswith(".c") else "c++"
            rec = collect_real_record(frag, erroneous, target, verifier,
                                      split=split, language=lang, result=res,
                                      project=project)
            if rec is not None:
                return rec, frag
        return None

    out: list[Record] = []
    source_counts: Counter[str] = Counter()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        i = 0
        block = max(1, workers) * 4
        while i < len(targets) and len(out) < max_instances:
            chunk = targets[i:i + block]
            i += len(chunk)
            blocked = frozenset(
                path for path, count in source_counts.items()
                if max_instances_per_source > 0 and
                count >= max_instances_per_source)
            for target, res in zip(chunk, ex.map(
                    lambda t: work(t, blocked), chunk)):
                if res is None:
                    continue
                rec, frag = res
                if (max_instances_per_source > 0 and
                        source_counts[frag.rel_path] >= max_instances_per_source):
                    now_blocked = frozenset(
                        path for path, count in source_counts.items()
                        if count >= max_instances_per_source)
                    retry = work(target, now_blocked)
                    if retry is None:
                        continue
                    rec, frag = retry
                out.append(rec)
                source_counts[frag.rel_path] += 1
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
        "project": rec.provenance.source.split(":", 1)[0],
        "source_path": fragment.rel_path,
        "region": list(fragment.span),
        "region_type": fragment.region_type,
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
    ap.add_argument("--project", default="llvm",
                    help="project name stored in provenance (works with any compile DB)")
    ap.add_argument("--model", default="gpt-5.4-mini")
    ap.add_argument("--base-url", default="https://api.openai.com/v1")
    ap.add_argument("--n-files", type=int, default=300)
    ap.add_argument("--candidates-per-target", type=int, default=4)
    ap.add_argument("--max-instances", type=int, default=300)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--source-substr", default="external/llvm-project",
                    help="path must contain this; use an empty string for another project")
    ap.add_argument("--language", choices=("all", "c", "c++"), default="all",
                    help="optionally build a C-only or C++-only corpus")
    ap.add_argument("--min-region-lines", type=int, default=3)
    ap.add_argument("--max-regions-per-file", type=int, default=40,
                    help="how many function spans to take per source file "
                         "(cap=6 wasted ~80%% of real functions)")
    ap.add_argument("--index-workers", type=int, default=16)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--max-instances-per-source", type=int, default=5,
                    help="diversity cap per translation unit; 0 disables")
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--existing-realcorpus", type=Path, action="append", default=[],
                    help="prior Record/run_sweep JSONL; its diagnostics are deprioritized")
    ap.add_argument("--target-order", choices=("real-gap-first", "covered-first", "catalog"),
                    default="real-gap-first")
    ap.add_argument("--target-names", type=Path,
                    help="optional one-diagnostic-name-per-line target allowlist")
    ap.add_argument("--include-invocation", action="store_true",
                    help="also try Driver/Frontend/etc. diagnostics that normally "
                         "cannot be induced by a source edit")
    ap.add_argument("--attempt-log", type=Path,
                    help="JSONL audit of every model/verification attempt and failure")
    ap.add_argument("--near-miss-out", type=Path,
                    help="optional run_sweep JSONL for valid non-target errors")
    args = ap.parse_args()

    verifier = FuzzlangClangVerifier(clang_bin=args.clang_bin,
                                     diagtool_bin=args.diagtool_bin, timeout_s=30.0)
    db = load_compile_db(args.compile_db)
    print(f"[realcorpus] compile db: {len(db)} TUs", flush=True)
    def _keep(p):
        if args.source_substr and args.source_substr not in p:
            return False
        if is_test_path(p):
            return False
        lower = p.lower()
        if args.language == "c" and not lower.endswith(".c"):
            return False
        if args.language == "c++" and lower.endswith(".c"):
            return False
        return True
    frags = build_fragment_index(db, verifier, n_files=args.n_files, seed=args.seed,
                                 min_region_lines=args.min_region_lines,
                                 max_regions_per_file=args.max_regions_per_file,
                                 path_filter=_keep, workers=args.index_workers)
    print(f"[realcorpus] fragment pool: {len(frags)} fragments", flush=True)

    out_of_scope = {l.strip() for l in args.out_of_scope.read_text().splitlines()
                    if l.strip()}
    exemplars = load_exemplars(args.dataset)
    observed = load_observed_names(args.existing_realcorpus)
    include_names = None
    if args.target_names:
        include_names = {line.strip() for line in args.target_names.read_text().splitlines()
                         if line.strip()}
    if args.language != "all":
        languages = load_diagnostic_languages(args.dataset)
        language_names = {name for name, langs in languages.items()
                          if args.language in langs}
        include_names = (language_names if include_names is None else
                         include_names & language_names)
    targets = build_targets(
        load_catalog().errors(), out_of_scope, exemplars,
        observed_names=observed, order_mode=args.target_order,
        include_names=include_names,
        exclude_components=(None if args.include_invocation else
                            INVOCATION_COMPONENTS))
    print(f"[realcorpus] targets: {len(targets)} in-scope "
          f"({sum(t.covered for t in targets)} with exemplars; "
          f"{sum(t.observed_in_real for t in targets)} previously observed)", flush=True)

    chat = _chat_fn(args.model, args.base_url)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    out_f = args.out.open("w")
    io_lock = threading.Lock()
    attempt_f = None
    near_f = None
    near_ids: set[str] = set()
    near_count = 0
    if args.attempt_log:
        args.attempt_log.parent.mkdir(parents=True, exist_ok=True)
        attempt_f = args.attempt_log.open("w")
    if args.near_miss_out:
        args.near_miss_out.parent.mkdir(parents=True, exist_ok=True)
        near_f = args.near_miss_out.open("w")

    def on_emit(rec, frag):
        # Stream each verified instance to disk immediately (flushed), so a run
        # killed mid-way (login-node long jobs can be) keeps what it produced.
        # on_emit runs only on the consumer/main thread, so no lock is needed.
        row = to_run_sweep_row(rec, frag)
        rows.append(row)
        out_f.write(json.dumps(row) + "\n")
        out_f.flush()
        det = rec.provenance.detail
        print(f"[realcorpus] {len(rows)}/{args.max_instances} {det['target_diag']} "
              f"match={det['primary_matches_target']} cascade={det['cascade_size']}",
              flush=True)

    def on_attempt(event):
        if attempt_f is None:
            return
        event = {"project": args.project, **event}
        with io_lock:
            attempt_f.write(json.dumps(event) + "\n")
            attempt_f.flush()

    def on_near_miss(target, frag, mutant, res):
        nonlocal near_count
        if near_f is None:
            return
        lang = "c" if frag.rel_path.endswith(".c") else "c++"
        rec = collect_real_record(
            frag, mutant, target, verifier, split=Split.EVAL, language=lang,
            result=res, project=args.project)
        if rec is None:
            return
        with io_lock:
            if rec.record_id in near_ids:
                return
            near_ids.add(rec.record_id)
            near_f.write(json.dumps(to_run_sweep_row(rec, frag)) + "\n")
            near_f.flush()
            near_count += 1

    try:
        drive_targets(
            targets, frags, verifier, chat=chat,
            candidates_per_target=args.candidates_per_target,
            max_instances=args.max_instances, workers=args.workers,
            max_attempts=args.max_attempts, temperature=args.temperature,
            on_emit=on_emit, on_attempt=on_attempt,
            on_near_miss=on_near_miss,
            max_instances_per_source=args.max_instances_per_source,
            project=args.project,
        )
    finally:
        out_f.close()
        if attempt_f is not None:
            attempt_f.close()
        if near_f is not None:
            near_f.close()
    matched = sum(1 for r in rows if r["primary_matches_target"])
    print(f"[realcorpus] DONE wrote {len(rows)} rows -> {args.out} "
          f"({matched} primary==target; {near_count} near misses)", flush=True)


if __name__ == "__main__":
    main()
