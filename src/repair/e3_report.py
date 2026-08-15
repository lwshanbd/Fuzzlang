"""Aggregate E3 adapter evaluations into the dataset-value table.

E3 asks whether fine-tuning on FuzzLang-built data repairs more real
compilation errors than an equal budget of data built by other methods, and
whether that holds on a project the training data never touched. This module
turns the per-(arm, seed, cohort) evaluation files into that table.

Three reporting rules are load-bearing:

* seeds are aggregated as mean +/- standard deviation *and* as a bootstrap
  interval over the pooled instances, because three seeds alone cannot
  separate a small difference from noise;
* comparisons against the base model and against the Mechanical control are
  **paired per instance**, since every arm sees the identical cohort;
* the unseen-project cohort is broken out by project and by language, because
  it mixes a project shift with a C/C++ language shift and the two must not be
  reported as one effect.
"""
from __future__ import annotations

import json
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Sequence

BASE_ARM = "base"
CONTROL_ARM = "mechanical"


def parse_eval_filename(name: str) -> tuple[str, str | None, str]:
    """Split ``<arm>-seed<N>--<cohort>.json`` into (arm, seed, cohort)."""
    stem = name[:-len(".json")] if name.endswith(".json") else name
    config, _, cohort = stem.partition("--")
    if not cohort:
        raise ValueError(f"evaluation file {name!r} has no --<cohort> suffix")
    arm, marker, seed = config.partition("-seed")
    return (arm, seed, cohort) if marker else (config, None, cohort)


def load_instances(path: Path) -> list[dict]:
    """Per-instance rows sit beside the summary as ``.instances.jsonl``."""
    companion = path.with_suffix("").with_suffix(".instances.jsonl")
    if not companion.is_file():
        companion = Path(str(path)[:-len(".json")] + ".instances.jsonl")
    if not companion.is_file():
        return []
    return [
        json.loads(line)
        for line in companion.read_text().splitlines() if line.strip()
    ]


def _bootstrap(values: Sequence[int], *, samples: int, seed: int) -> tuple[float, float] | None:
    if not values:
        return None
    rng = random.Random(seed)
    size = len(values)
    means = sorted(
        sum(values[rng.randrange(size)] for _ in range(size)) / size
        for _ in range(samples)
    )
    return (
        round(means[max(0, int(0.025 * samples) - 1)], 4),
        round(means[min(samples - 1, int(0.975 * samples))], 4),
    )


def _paired_difference(
    arm_rows: Mapping[str, dict], other_rows: Mapping[str, dict],
    *, samples: int, seed: int,
) -> dict | None:
    """Instance-level difference over the records both configurations saw."""
    shared = sorted(set(arm_rows) & set(other_rows))
    if not shared:
        return None
    deltas = [
        int(bool(arm_rows[key].get("compile_ok")))
        - int(bool(other_rows[key].get("compile_ok")))
        for key in shared
    ]
    wins = sum(1 for d in deltas if d > 0)
    losses = sum(1 for d in deltas if d < 0)
    return {
        "paired_instances": len(shared),
        "mean_difference": round(sum(deltas) / len(deltas), 4),
        "ci95": _bootstrap(deltas, samples=samples, seed=seed),
        "wins": wins,
        "losses": losses,
        "ties": len(shared) - wins - losses,
    }


def _breakdown(rows: Iterable[dict], key: str) -> dict[str, dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or "?")].append(row)
    return {
        name: {
            "n": len(items),
            "verified_fix_rate": round(
                sum(bool(i.get("compile_ok")) for i in items) / len(items), 4
            ),
        }
        for name, items in sorted(grouped.items())
    }


def build_e3_report(
    eval_dir: Path, *, bootstrap_samples: int = 2000, seed: int = 20260809,
) -> dict:
    """Assemble the per-cohort arm table with paired differences."""
    by_cohort: dict[str, dict[str, dict[str | None, list[dict]]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    summaries: dict[tuple[str, str | None, str], dict] = {}
    for path in sorted(Path(eval_dir).glob("*--*.json")):
        arm, arm_seed, cohort = parse_eval_filename(path.name)
        summaries[(arm, arm_seed, cohort)] = json.loads(path.read_text())
        by_cohort[cohort][arm][arm_seed] = load_instances(path)

    report: dict = {"schema": "fuzzlang.e3_report.v1", "cohorts": {}}
    for cohort, arms in sorted(by_cohort.items()):
        pooled: dict[str, list[dict]] = {
            arm: [row for rows in seeds.values() for row in rows]
            for arm, seeds in arms.items()
        }
        # Pair on the first seed of each arm so every configuration is compared
        # on identical records rather than on pooled averages.
        first_seed_rows: dict[str, dict[str, dict]] = {
            arm: {
                str(row.get("record_id")): row
                for row in seeds[sorted(seeds, key=lambda s: (s is None, s))[0]]
            }
            for arm, seeds in arms.items() if seeds
        }
        table = []
        for arm, seeds in sorted(arms.items()):
            per_seed = [
                sum(bool(r.get("compile_ok")) for r in rows) / len(rows)
                for rows in seeds.values() if rows
            ]
            rows = pooled[arm]
            flags = [int(bool(r.get("compile_ok"))) for r in rows]
            entry = {
                "arm": arm,
                "seeds": sorted(s for s in seeds if s is not None) or ["n/a"],
                "instances_per_seed": (
                    len(next(iter(seeds.values()))) if seeds else 0
                ),
                "verified_fix_rate_mean": (
                    round(statistics.fmean(per_seed), 4) if per_seed else 0.0
                ),
                "verified_fix_rate_std": (
                    round(statistics.pstdev(per_seed), 4) if len(per_seed) > 1 else 0.0
                ),
                "verified_fix_rate_pooled": (
                    round(sum(flags) / len(flags), 4) if flags else 0.0
                ),
                "verified_fix_rate_ci95": _bootstrap(
                    flags, samples=bootstrap_samples, seed=seed,
                ),
                "exact_match_rate_pooled": (
                    round(
                        sum(bool(r.get("exact_match")) for r in rows) / len(rows), 4
                    ) if rows else 0.0
                ),
                "parse_rate_pooled": (
                    round(sum(bool(r.get("parse_ok")) for r in rows) / len(rows), 4)
                    if rows else 0.0
                ),
                "by_project": _breakdown(rows, "project"),
                "by_language": _breakdown(rows, "language"),
            }
            for other, label in ((BASE_ARM, "vs_base"), (CONTROL_ARM, "vs_mechanical")):
                if arm != other and other in first_seed_rows and arm in first_seed_rows:
                    entry[label] = _paired_difference(
                        first_seed_rows[arm], first_seed_rows[other],
                        samples=bootstrap_samples, seed=seed + 1,
                    )
            table.append(entry)
        report["cohorts"][cohort] = {"table": table}
    report["sample"] = {
        "cohorts": sorted(report["cohorts"]),
        "note": (
            "Three seeds bound run-to-run variance, not corpus variance; the "
            "bootstrap interval is over instances from a single fixed cohort."
        ),
    }
    return report
