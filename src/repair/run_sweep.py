#!/usr/bin/env python3
"""Inference-side driver for one (method, seed) cell of the main sweep.

Loads the NatErr eval split, instantiates the named method from
`repair.methods`, runs each instance through the DVCR harness with a
vLLM-backed policy pointing at `--base-url`, collects per-instance
VerifiedResult records, writes a summary JSON.

Called from scripts/polaris_qsub_sweep.sh. Requires a running vLLM server
(the PBS script starts one on localhost).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

from repair.agent import (
    MockChatBackend,  # for --dry-run without a real server
    OpenAICompatPolicy,
    OpenAIChatBackend,
)
from repair.eval.metrics import (
    InstanceResult,
    diag_family_from_name,
    summarize,
)
from repair.methods import (
    make_b0_runner,
    make_b1_runner,
    make_b2_runner,
    make_b3_runner,
    make_dvcr_no_id_runner,
    make_dvcr_no_loop_runner,
    make_dvcr_no_structure_runner,
    make_dvcr_runner,
)
from foundation.verifier import FuzzlangClangVerifier


_METHOD_FACTORIES = {
    "b0_zero_shot": make_b0_runner,
    "b1_stderr_loop": make_b1_runner,
    "b2_static_sft": make_b2_runner,
    "b3_sft_stderr_loop": make_b3_runner,
    "dvcr": make_dvcr_runner,
    "dvcr_no_id": make_dvcr_no_id_runner,
    "dvcr_no_structure": make_dvcr_no_structure_runner,
    "dvcr_no_loop": make_dvcr_no_loop_runner,
}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--method", required=True, choices=list(_METHOD_FACTORIES))
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--split", required=True, help="JSONL eval split (NatErr or HPC).")
    p.add_argument("--model-name", required=True)
    p.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    p.add_argument("--T", type=int, default=5)
    p.add_argument("--K", type=int, default=4)
    p.add_argument("--token-envelope", type=int, default=5120)
    p.add_argument("--clang-bin", required=True)
    p.add_argument("--diagtool-bin", required=True)
    p.add_argument("--adapter-name", default=None,
                   help="LoRA adapter name as registered with vLLM (for B2/B3).")
    p.add_argument("--out", required=True, help="Output JSON summary path.")
    p.add_argument("--max-instances", type=int, default=None,
                   help="Cap for smoke / dry-run.")
    p.add_argument("--dry-run", action="store_true",
                   help="Use a MockChatBackend that always returns an empty edit.")
    return p.parse_args()


def _load_split(path: Path, max_n: int | None) -> list[dict]:
    rows: list[dict] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
            if max_n is not None and len(rows) >= max_n:
                break
    return rows


def _make_backend(args):
    if args.dry_run:
        return MockChatBackend(scripted_responses=[])
    model_name = args.adapter_name or args.model_name
    return OpenAIChatBackend(model_name=model_name, base_url=args.base_url)


def _make_runner(args, verifier, policy):
    factory = _METHOD_FACTORIES[args.method]
    kwargs: dict = {"token_envelope": args.token_envelope}
    sig = getattr(factory, "__annotations__", {})
    # b0/b2 single-shot don't take T/K; the DVCR family does.
    if args.method not in ("b0_zero_shot", "b2_static_sft"):
        kwargs["T"] = args.T
        kwargs["K"] = args.K
    return factory(verifier, policy, **kwargs)


def main() -> int:
    args = _parse_args()
    random.seed(args.seed)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    split = _load_split(Path(args.split), args.max_instances)
    print(f"[run_sweep] method={args.method} seed={args.seed} n={len(split)}",
          flush=True)

    verifier = FuzzlangClangVerifier(
        clang_bin=args.clang_bin, diagtool_bin=args.diagtool_bin, timeout_s=15.0,
    )
    backend = _make_backend(args)
    policy = OpenAICompatPolicy(backend)
    runner = _make_runner(args, verifier, policy)

    t0 = time.time()
    results: list[InstanceResult] = []
    for i, inst in enumerate(split):
        src = inst["buggy_src"]
        cmd = inst["compile_cmd"]            # list[str] with PLACEHOLDER for the file.
        inst_id = inst.get("instance_id", f"idx_{i}")
        gt_diag_id = inst.get("diag_id")
        gt_diag_name = inst.get("diag_name")

        try:
            r = runner(src, cmd)
        except Exception as e:            # robust against policy / verifier crashes.
            print(f"[run_sweep]   {inst_id}: error {type(e).__name__}: {e}",
                  flush=True)
            results.append(InstanceResult(
                instance_id=inst_id, diag_id=gt_diag_id,
                diag_family=diag_family_from_name(gt_diag_name),
                ok=False, turns_used=0, tokens_used=0,
                reason=f"exception:{type(e).__name__}",
            ))
            continue

        results.append(InstanceResult(
            instance_id=inst_id, diag_id=gt_diag_id,
            diag_family=diag_family_from_name(gt_diag_name),
            ok=r.ok, turns_used=r.turns_used, tokens_used=r.output_tokens_used,
            reason=r.reason.value,
        ))
        if (i + 1) % 50 == 0:
            fix_rate = sum(1 for x in results if x.ok) / len(results)
            print(f"[run_sweep]   {i+1}/{len(split)}  fix_rate={fix_rate:.3f}",
                  flush=True)

    elapsed = time.time() - t0
    summary = summarize(results, seed=args.seed, n_resamples=10_000)
    summary.update({
        "method": args.method,
        "seed": args.seed,
        "n_instances": len(results),
        "elapsed_sec": round(elapsed, 2),
        "split": args.split,
        "model_name": args.model_name,
        "adapter": args.adapter_name,
        "T": args.T,
        "K": args.K,
        "token_envelope": args.token_envelope,
    })
    # Rewrite per_family as a JSON-friendly dict (tuples are not JSON).
    summary["per_family"] = {k: {"ok": v[0], "n": v[1], "rate": v[2]}
                             for k, v in summary["per_family"].items()}

    out.write_text(json.dumps(summary, indent=2, sort_keys=True))
    per_inst = out.with_suffix(".instances.jsonl")
    with per_inst.open("w") as f:
        for r in results:
            f.write(json.dumps({
                "instance_id": r.instance_id,
                "diag_id": r.diag_id,
                "diag_family": r.diag_family,
                "ok": r.ok,
                "turns_used": r.turns_used,
                "tokens_used": r.tokens_used,
                "reason": r.reason,
            }) + "\n")

    print(f"[run_sweep] DONE  fix_rate(micro)={summary['verified_fix_rate_micro']:.3f} "
          f"CI95={summary['verified_fix_rate_micro_ci95']} "
          f"elapsed={elapsed:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
