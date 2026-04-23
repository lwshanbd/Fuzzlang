"""Evaluation metrics for DVCR and baselines.

Primary: verified_fix_rate@T=K (compiler-verified SUCCESS within T turns).
Reporting: 95% bootstrap CI with 10k resamples, macro-vs-micro, per-family.
"""
from __future__ import annotations

import random
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence


@dataclass(frozen=True)
class InstanceResult:
    """One evaluation instance's outcome."""

    instance_id: str                    # stable, matches NatErr manifest.
    diag_id: Optional[int]              # ground-truth initial diagnostic.
    diag_family: Optional[str]          # e.g. "err_expected" for err_expected_semi.
    ok: bool                            # did the method verify_fix the instance?
    turns_used: int
    tokens_used: int
    reason: str                         # TerminalReason.value


def diag_family_from_name(diag_name: Optional[str]) -> Optional[str]:
    """Coarse family grouping: drop the trailing `_specific` component.

    `err_expected_semi` -> `err_expected`, `err_undeclared_var` -> `err_undeclared`.
    Not a formal Clang taxonomy — just a coarse bucket for macro-vs-micro check.
    """
    if not diag_name:
        return None
    # Keep all but the final token after '_'. If fewer than 3 components, keep the whole name.
    parts = diag_name.split("_")
    if len(parts) <= 2:
        return diag_name
    return "_".join(parts[:-1])


def verified_fix_rate(results: Sequence[InstanceResult]) -> float:
    """Micro-average: fraction of instances that verified OK."""
    if not results:
        return 0.0
    return sum(1 for r in results if r.ok) / len(results)


def per_family_rate(
    results: Sequence[InstanceResult],
) -> dict[str, tuple[int, int, float]]:
    """Return {family -> (n_ok, n_total, rate)}."""
    buckets: dict[str, list[InstanceResult]] = defaultdict(list)
    for r in results:
        fam = r.diag_family or "__unknown__"
        buckets[fam].append(r)
    out: dict[str, tuple[int, int, float]] = {}
    for fam, xs in buckets.items():
        n = len(xs)
        k = sum(1 for x in xs if x.ok)
        out[fam] = (k, n, k / n if n else 0.0)
    return out


def macro_avg_by_family(results: Sequence[InstanceResult]) -> float:
    """Unweighted mean of per-family verified_fix_rate.

    Exposes head-class inflation: if micro-average is much larger than macro,
    a few common diagnostics dominate the headline number.
    """
    pf = per_family_rate(results)
    if not pf:
        return 0.0
    return sum(rate for (_, _, rate) in pf.values()) / len(pf)


def bootstrap_ci(
    results: Sequence[InstanceResult],
    *,
    n_resamples: int = 10_000,
    alpha: float = 0.05,
    seed: int = 0,
    metric: str = "verified_fix_rate",
) -> tuple[float, float, float]:
    """Return (point_estimate, lower, upper) for the chosen metric.

    Percentile bootstrap. Default 95% CI (alpha=0.05).
    Supported metrics: "verified_fix_rate", "macro_avg_by_family".
    """
    n = len(results)
    if n == 0:
        return 0.0, 0.0, 0.0
    rng = random.Random(seed)
    indices = list(range(n))
    samples: list[float] = []

    fn = verified_fix_rate if metric == "verified_fix_rate" else macro_avg_by_family

    for _ in range(n_resamples):
        resample = [results[rng.choice(indices)] for _ in range(n)]
        samples.append(fn(resample))

    samples.sort()
    lo = samples[int(alpha / 2 * n_resamples)]
    hi = samples[int((1 - alpha / 2) * n_resamples)]
    point = fn(results)
    return point, lo, hi


def stratified_bootstrap_ci(
    results: Sequence[InstanceResult],
    *,
    n_resamples: int = 10_000,
    alpha: float = 0.05,
    seed: int = 0,
) -> tuple[float, float, float]:
    """Like bootstrap_ci but resamples within each diagnostic family.

    Preserves family proportions across resamples; useful when the CI width on
    `verified_fix_rate` is dominated by family-distribution variance rather
    than per-family variance.
    """
    by_family: dict[str, list[InstanceResult]] = defaultdict(list)
    for r in results:
        by_family[r.diag_family or "__unknown__"].append(r)

    if not by_family:
        return 0.0, 0.0, 0.0

    rng = random.Random(seed)
    samples: list[float] = []

    for _ in range(n_resamples):
        resample: list[InstanceResult] = []
        for fam, xs in by_family.items():
            n_fam = len(xs)
            idx = [rng.randrange(n_fam) for _ in range(n_fam)]
            resample.extend(xs[i] for i in idx)
        samples.append(verified_fix_rate(resample))

    samples.sort()
    lo = samples[int(alpha / 2 * n_resamples)]
    hi = samples[int((1 - alpha / 2) * n_resamples)]
    point = verified_fix_rate(results)
    return point, lo, hi


def summarize(
    results: Sequence[InstanceResult],
    *,
    seed: int = 0,
    n_resamples: int = 10_000,
) -> dict:
    """One-call summary for a table row. Returns the fields the paper reports."""
    micro, micro_lo, micro_hi = bootstrap_ci(
        results, n_resamples=n_resamples, seed=seed, metric="verified_fix_rate"
    )
    macro, macro_lo, macro_hi = bootstrap_ci(
        results, n_resamples=n_resamples, seed=seed, metric="macro_avg_by_family"
    )
    total_tokens = sum(r.tokens_used for r in results)
    avg_turns = (
        sum(r.turns_used for r in results) / len(results) if results else 0.0
    )
    per_family = per_family_rate(results)
    return {
        "n": len(results),
        "verified_fix_rate_micro": micro,
        "verified_fix_rate_micro_ci95": (micro_lo, micro_hi),
        "verified_fix_rate_macro": macro,
        "verified_fix_rate_macro_ci95": (macro_lo, macro_hi),
        "total_output_tokens": total_tokens,
        "avg_turns": avg_turns,
        "per_family": per_family,
    }
