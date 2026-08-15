"""Turn a completed E1 run into the metric table the plan requires.

The plan asks E1 to report exact-target rate, accepted records per diagnostic,
yield per output token and per GPU hour, new strict coverage, held-out and
cross-project transfer, and the failure-mode breakdown.  This module computes
exactly those from the archived comparison and attempt logs, and refuses to
call a small sample a conclusion.
"""
from __future__ import annotations

import random
from collections import Counter, defaultdict
from typing import Iterable, Mapping, Sequence

# Below this many target diagnostics per arm the paired difference is not
# separable from sampling noise at the effect sizes E1 cares about, so the
# report labels itself a smoke rather than a result.
MIN_TARGETS_FOR_CONCLUSION = 60


def failure_mode_counts(attempts: Iterable[Mapping]) -> dict[str, dict[str, int]]:
    """Rejection reasons per arm, most frequent first."""
    counters: dict[str, Counter] = defaultdict(Counter)
    for attempt in attempts:
        if attempt.get("status") != "rejected":
            continue
        reason = attempt.get("reason")
        if reason:
            counters[attempt["arm"]][reason] += 1
    return {
        arm: dict(counter.most_common()) for arm, counter in sorted(counters.items())
    }


def new_strict_coverage(
    per_target: Mapping[str, Mapping[str, Mapping]],
    *,
    arm: str,
    covered: Iterable[str],
) -> dict:
    """Diagnostics this arm produced a record for, and which are genuinely new."""
    known = set(covered)
    produced = sorted(
        target for target, arms in per_target.items()
        if (arms.get(arm) or {}).get("accepted_records", 0) > 0
    )
    new = sorted(name for name in produced if name not in known)
    return {
        "covered_types": len(produced), "new_types": len(new), "new_names": new,
    }


def _bootstrap_ci(
    values: Sequence[float], *, samples: int, seed: int,
) -> tuple[float, float] | None:
    """Percentile bootstrap interval for a mean over diagnostics."""
    if not values:
        return None
    rng = random.Random(seed)
    size = len(values)
    means = sorted(
        sum(values[rng.randrange(size)] for _ in range(size)) / size
        for _ in range(samples)
    )
    low = means[max(0, int(0.025 * samples) - 1)]
    high = means[min(samples - 1, int(0.975 * samples))]
    return round(low, 4), round(high, 4)


def _macro(values: Sequence[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def build_e1_report(
    comparison: Mapping,
    *,
    attempts: Iterable[Mapping],
    covered: Iterable[str],
    bootstrap_samples: int = 2000,
    seed: int = 20260807,
) -> dict:
    """Assemble the arm table, the paired difference, and the honesty caveat."""
    per_target = comparison["per_target"]
    attempts = list(attempts)
    known = set(covered)
    table = []
    for summary in comparison["arms"]:
        arm = summary["arm"]
        stats = [
            arms[arm] for arms in per_target.values() if arm in arms
        ]
        exact = [item["exact_target_rate_per_source"] for item in stats]
        transfer = [
            item["transfer_rate"] for item in stats
            if item.get("transfer_rate") is not None
        ]
        held_out = [
            _held_out_rate(item) for item in stats
            if _held_out_rate(item) is not None
        ]
        budget, efficiency = summary["budget"], summary["efficiency"]
        table.append({
            "arm": arm,
            "targets": summary["targets"],
            "targets_with_accepted_record": summary["targets_with_accepted_record"],
            "target_hit_rate": summary["target_hit_rate"],
            "accepted_records": summary["accepted_records"],
            "accepted_injectors": summary["accepted_injectors"],
            "records_per_target": round(
                summary["accepted_records"] / summary["targets"], 4
            ) if summary["targets"] else 0.0,
            "macro_exact_target_rate": _macro(exact),
            "macro_exact_target_rate_ci95": _bootstrap_ci(
                exact, samples=bootstrap_samples, seed=seed,
            ),
            "macro_held_out_source_rate": _macro(held_out),
            "macro_cross_project_transfer_rate": _macro(transfer),
            "macro_cross_project_transfer_rate_ci95": _bootstrap_ci(
                transfer, samples=bootstrap_samples, seed=seed + 1,
            ),
            "model_calls": budget["model_calls"],
            "output_tokens": budget["output_tokens"],
            "model_seconds": budget["model_seconds"],
            "wall_seconds": summary.get("wall_seconds"),
            "compiler_invocations": budget["compiler_invocations"],
            "records_per_1k_output_tokens": efficiency["records_per_1k_output_tokens"],
            "records_per_gpu_hour": efficiency["records_per_gpu_hour"],
            "output_tokens_per_accepted_record": efficiency[
                "output_tokens_per_accepted_record"
            ],
            "compiler_invocations_per_accepted_record": efficiency[
                "compiler_invocations_per_accepted_record"
            ],
            "model_calls_per_accepted_record": efficiency[
                "model_calls_per_accepted_record"
            ],
            "coverage": new_strict_coverage(per_target, arm=arm, covered=known),
        })

    targets = max((row["targets"] for row in table), default=0)
    return {
        "schema": "fuzzlang.e1_report.v1",
        "table": table,
        "paired_difference": _paired_difference(
            per_target, bootstrap_samples=bootstrap_samples, seed=seed,
        ),
        "failure_modes": failure_mode_counts(attempts),
        "per_target": per_target,
        "sample": {
            "targets": targets,
            "minimum_targets_for_conclusion": MIN_TARGETS_FOR_CONCLUSION,
            "sufficient_for_conclusion": targets >= MIN_TARGETS_FOR_CONCLUSION,
            "interpretation": (
                "Sample meets the predeclared minimum; report intervals, not "
                "point estimates alone."
                if targets >= MIN_TARGETS_FOR_CONCLUSION else
                "Smoke-scale sample: use it to validate budget accounting, "
                "verification, and statistics, not to state a method result."
            ),
        },
    }


def _held_out_rate(stats: Mapping) -> float | None:
    """Accepted-record rate over sources that were not Injector evidence.

    For the Injector arm this is the honest reuse measurement, since the first
    sources also supplied the synthesis prompt.  The DirectEdit arm is scored
    on the same source split so the two remain comparable.
    """
    return stats.get("held_out_source_rate")


def _paired_difference(
    per_target: Mapping[str, Mapping[str, Mapping]],
    *,
    bootstrap_samples: int,
    seed: int,
) -> dict:
    """Injector minus DirectEdit on the diagnostics both arms actually ran."""
    paired = [
        (arms["injector"], arms["direct_edit"])
        for arms in per_target.values()
        if "injector" in arms and "direct_edit" in arms
    ]
    if not paired:
        return {"paired_targets": 0}
    exact = [
        injector["exact_target_rate_per_source"]
        - direct["exact_target_rate_per_source"]
        for injector, direct in paired
    ]
    records = [
        injector["accepted_records"] - direct["accepted_records"]
        for injector, direct in paired
    ]
    return {
        "paired_targets": len(paired),
        "mean_exact_target_rate_difference": _macro(exact),
        "mean_exact_target_rate_difference_ci95": _bootstrap_ci(
            exact, samples=bootstrap_samples, seed=seed + 2,
        ),
        "mean_accepted_record_difference": _macro(records),
        "mean_accepted_record_difference_ci95": _bootstrap_ci(
            records, samples=bootstrap_samples, seed=seed + 3,
        ),
        "injector_only_targets": sorted(
            target for target, arms in per_target.items()
            if arms.get("injector", {}).get("accepted_records", 0) > 0
            and arms.get("direct_edit", {}).get("accepted_records", 0) == 0
        ),
        "direct_edit_only_targets": sorted(
            target for target, arms in per_target.items()
            if arms.get("direct_edit", {}).get("accepted_records", 0) > 0
            and arms.get("injector", {}).get("accepted_records", 0) == 0
        ),
    }


def replay_arm_summary(
    records: Iterable[Mapping],
    *,
    exclude_vendored: bool = False,
) -> dict:
    """Recount one library-replay arm directly from its records.

    The arm manifest and ``injector_reach.json`` are written during generation
    and store only aggregate counts, so any filter applied afterwards -- notably
    dropping fetched dependencies that were attributed to the project that
    vendored them -- has to recount from the records.  This produces the same
    fields the manifest carries, plus how many records the filter removed.
    """
    from gen.realcorpus.corpus import is_vendored_path

    diagnostics: set[str] = set()
    projects: set[str] = set()
    sources: set[str] = set()
    reach: dict[str, set[str]] = defaultdict(set)
    reach_projects: dict[str, set[str]] = defaultdict(set)
    per_project: dict[str, dict[str, set]] = defaultdict(
        lambda: {"records": set(), "diagnostics": set(), "source_tus": set()}
    )
    kept = 0
    excluded = 0
    for record in records:
        detail = (record.get("provenance") or {}).get("detail") or {}
        path = str(detail.get("source_path") or "")
        if exclude_vendored and is_vendored_path(path):
            excluded += 1
            continue
        kept += 1
        diag = str(detail.get("target_diag") or "")
        project = str(detail.get("project") or "?")
        injector = str(detail.get("injector_id") or "")
        diagnostics.add(diag)
        projects.add(project)
        sources.add(path)
        reach[injector].add(path)
        reach_projects[injector].add(project)
        bucket = per_project[project]
        bucket["records"].add(str(record.get("record_id")))
        bucket["diagnostics"].add(diag)
        bucket["source_tus"].add(path)

    counts = sorted((len(paths) for paths in reach.values()), reverse=True)
    return {
        "records": kept,
        "excluded_vendored": excluded,
        "diagnostics": len(diagnostics),
        "projects": len(projects),
        "source_tus": len(sources),
        "injectors_with_a_record": len(reach),
        "sources_per_injector_mean": (
            round(sum(counts) / len(counts), 3) if counts else 0.0
        ),
        "sources_per_injector_max": counts[0] if counts else 0,
        "injectors_reaching_multiple_sources": sum(1 for n in counts if n > 1),
        "injectors_reaching_multiple_projects": sum(
            1 for names in reach_projects.values() if len(names) > 1
        ),
        "per_project_records": {
            project: {
                "records": len(bucket["records"]),
                "diagnostics": len(bucket["diagnostics"]),
                "source_tus": len(bucket["source_tus"]),
            }
            for project, bucket in sorted(per_project.items())
        },
        "diagnostic_names": sorted(diagnostics),
    }
