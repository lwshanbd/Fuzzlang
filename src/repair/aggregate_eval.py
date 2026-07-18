#!/usr/bin/env python3
"""Aggregate run_sweep cells (method x seed) into a paper-ready table.

Reads every ``<method>_s<seed>.json`` summary and its companion
``<method>_s<seed>.instances.jsonl`` in a run directory, then reports per method:

  * verified fix-rate, micro and macro, as mean +/- std across seeds AND a 95%
    bootstrap CI over the instance pool (all seeds concatenated);
  * mean turns and mean output tokens per instance (so the matched-budget claim
    is auditable);
  * the per-diagnostic-family breakdown, and the diag - b1 delta per family.

Emits a Markdown block on stdout (paste/append into the progress doc) and, with
--json, a machine-readable summary.

    PYTHONPATH=src python3 src/repair/aggregate_eval.py \
        --dir /p/lustre1/shan4/fuzzlang-repair/full
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

from repair.eval.metrics import (InstanceResult, bootstrap_ci,
                                 macro_avg_by_family, per_family_rate,
                                 verified_fix_rate)

# Display order + labels.
_ORDER = [
    ("b0_zero_shot", "b0  (zero-shot, single-shot)"),
    ("b1_stderr_loop", "b1  (stderr-text loop)"),
    ("diag", "diag  (typed diagnostic signal)"),
    ("diag_no_id", "  -id   (structure, no diag_id)"),
    ("diag_no_structure", "  -struct (raw stderr, diag loop)"),
]


def _load_instances(path: Path) -> list[InstanceResult]:
    out = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        out.append(InstanceResult(
            instance_id=d["instance_id"], diag_id=d.get("diag_id"),
            diag_family=d.get("diag_family"), ok=bool(d["ok"]),
            turns_used=int(d.get("turns_used", 0)),
            tokens_used=int(d.get("tokens_used", 0)),
            reason=d.get("reason", ""),
        ))
    return out


def _load_metadata(path: Path) -> dict[str, dict]:
    metadata: dict[str, dict] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        metadata[row["instance_id"]] = row
    return metadata


def slice_rates(
    results: list[InstanceResult], metadata: dict[str, dict], field: str,
) -> dict[str, dict[str, float | int]]:
    """Return pooled fix rates after joining instance results to eval metadata."""
    buckets: dict[str, list[InstanceResult]] = defaultdict(list)
    for result in results:
        value = metadata.get(result.instance_id, {}).get(field)
        buckets[str(value) if value is not None else "__unknown__"].append(result)
    return {
        label: {
            "ok": sum(result.ok for result in bucket),
            "n": len(bucket),
            "rate": verified_fix_rate(bucket),
        }
        for label, bucket in sorted(buckets.items())
    }


def _fmt_pct(x: float) -> str:
    return f"{100 * x:.1f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, required=True)
    ap.add_argument(
        "--split", type=Path, default=None,
        help="repair-ready eval JSONL; enables exact/near and cascade slices",
    )
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--n-resamples", type=int, default=10_000)
    args = ap.parse_args()

    d = args.dir
    metadata = _load_metadata(args.split) if args.split else {}
    present = []
    for method, _ in _ORDER:
        seeds = sorted(d.glob(f"{method}_s*.instances.jsonl"))
        if seeds:
            present.append((method, seeds))

    agg: dict[str, dict] = {}
    pooled: dict[str, list[InstanceResult]] = {}
    for method, seed_files in present:
        per_seed_micro, per_seed_macro, per_seed_turns, per_seed_tok = [], [], [], []
        pool: list[InstanceResult] = []
        for sf in seed_files:
            insts = _load_instances(sf)
            pool.extend(insts)
            per_seed_micro.append(verified_fix_rate(insts))
            per_seed_macro.append(macro_avg_by_family(insts))
            per_seed_turns.append(
                sum(i.turns_used for i in insts) / max(1, len(insts)))
            per_seed_tok.append(
                sum(i.tokens_used for i in insts) / max(1, len(insts)))
        micro_pt, micro_lo, micro_hi = bootstrap_ci(
            pool, n_resamples=args.n_resamples, seed=0,
            metric="verified_fix_rate")
        macro_pt, macro_lo, macro_hi = bootstrap_ci(
            pool, n_resamples=args.n_resamples, seed=0,
            metric="macro_avg_by_family")
        agg[method] = {
            "n_per_seed": len(seed_files) and len(pool) // len(seed_files),
            "seeds": len(seed_files),
            "micro_mean": statistics.mean(per_seed_micro),
            "micro_std": statistics.pstdev(per_seed_micro),
            "micro_pool": micro_pt, "micro_ci": (micro_lo, micro_hi),
            "macro_mean": statistics.mean(per_seed_macro),
            "macro_std": statistics.pstdev(per_seed_macro),
            "macro_pool": macro_pt, "macro_ci": (macro_lo, macro_hi),
            "mean_turns": statistics.mean(per_seed_turns),
            "mean_tokens": statistics.mean(per_seed_tok),
            "per_seed_micro": per_seed_micro,
        }
        if metadata:
            agg[method]["slices"] = {
                "generation_label": slice_rates(
                    pool, metadata, "generation_label"),
                "cascade_bucket": slice_rates(pool, metadata, "cascade_bucket"),
            }
        pooled[method] = pool

    # ---- Markdown table ----
    label = dict(_ORDER)
    lines = []
    n_any = next((agg[m]["n_per_seed"] for m, _ in present), 0)
    lines.append(f"Eval split: {n_any} reproducible instances, "
                 f"{agg[present[0][0]]['seeds'] if present else 0} seeds, "
                 f"matched budget E=5120 (T=5, K=4), verifier = patched clang 22.1.8.\n")
    lines.append("| method | verified fix-rate (micro) | 95% CI | macro | mean turns | mean out-tok |")
    lines.append("|---|---|---|---|---|---|")
    for method, _ in _ORDER:
        if method not in agg:
            continue
        a = agg[method]
        lines.append(
            f"| {label[method]} | "
            f"{_fmt_pct(a['micro_mean'])} +/- {_fmt_pct(a['micro_std'])} | "
            f"[{_fmt_pct(a['micro_ci'][0])}, {_fmt_pct(a['micro_ci'][1])}] | "
            f"{_fmt_pct(a['macro_mean'])} | "
            f"{a['mean_turns']:.2f} | {a['mean_tokens']:.0f} |")

    # ---- headline delta ----
    if "diag" in agg and "b1_stderr_loop" in agg:
        dd, bb = agg["diag"], agg["b1_stderr_loop"]
        delta = dd["micro_mean"] - bb["micro_mean"]
        per_seed_delta = [x - y for x, y in
                          zip(dd["per_seed_micro"], bb["per_seed_micro"])]
        lines.append("")
        lines.append(f"**diag - b1 = {_fmt_pct(delta)} pts** (micro; "
                     f"per-seed deltas: "
                     f"{', '.join(_fmt_pct(x) for x in per_seed_delta)}).")

    # ---- per-family breakdown (pooled), diag vs b1 ----
    if "diag" in pooled and "b1_stderr_loop" in pooled:
        fam_d = per_family_rate(pooled["diag"])
        fam_b = per_family_rate(pooled["b1_stderr_loop"])
        # rank families by instance count (per seed-pool)
        fams = sorted(fam_d, key=lambda f: -fam_d[f][1])[:15]
        lines.append("")
        lines.append("Per-family (top 15 by count), fix-rate diag vs b1:")
        lines.append("")
        lines.append("| family | n | diag | b1 | delta |")
        lines.append("|---|---|---|---|---|")
        for f in fams:
            kd, nd, rd = fam_d[f]
            kb, nb, rb = fam_b.get(f, (0, nd, 0.0))
            lines.append(f"| {f} | {nd // agg['diag']['seeds']} | "
                         f"{_fmt_pct(rd)} | {_fmt_pct(rb)} | "
                         f"{_fmt_pct(rd - rb)} |")

    # ---- generation and cascade slices (pooled across seeds) ----
    def append_slice_table(title: str, field: str, order: list[str]) -> None:
        if not metadata or not present:
            return
        methods = [method for method, _ in _ORDER if method in agg]
        lines.extend(["", title, ""])
        lines.append("| slice | n | " + " | ".join(methods) + " |")
        lines.append("|---|---:|" + "---:|" * len(methods))
        for bucket in order:
            available = [agg[m].get("slices", {}).get(field, {}).get(bucket)
                         for m in methods]
            if not any(available):
                continue
            base = next(item for item in available if item is not None)
            n_per_seed = int(base["n"]) // agg[methods[0]]["seeds"]
            rates = [
                _fmt_pct(float(item["rate"])) if item is not None else "--"
                for item in available
            ]
            lines.append(f"| {bucket} | {n_per_seed} | " +
                         " | ".join(rates) + " |")

    append_slice_table(
        "Fix-rate by generation label (pooled across seeds):",
        "generation_label", ["exact_target", "near_miss", "__unknown__"],
    )
    append_slice_table(
        "Fix-rate by initial diagnostic cascade size (pooled across seeds):",
        "cascade_bucket", ["1", "2-5", "6-10", ">10", "__unknown__"],
    )

    md = "\n".join(lines)
    print(md)
    if args.json:
        args.json.write_text(json.dumps(
            {k: {kk: vv for kk, vv in v.items() if kk != "per_seed_micro"}
             | {"per_seed_micro": v["per_seed_micro"]}
             for k, v in agg.items()}, indent=2))


if __name__ == "__main__":
    main()
