"""Turn the E5 scaling evaluations into a data-quantity curve.

E3 matched every construction arm to 557 records, because that is what the most
expensive arm could produce. FuzzLang can supply an order of magnitude more at
no extra cost, so E3's margin is a lower bound rather than a measurement of what
its data is worth. E5 trains the same arm at nested sizes and asks whether more
of it keeps helping.

Two reporting rules:

* the curve is ordered by **training records**, and each point states its
  increment over the *previous tier* rather than over the base model -- the
  question is what the extra data bought, not what fine-tuning bought;
* the un-finetuned base is reported beside the curve but never on it, since it
  is not a point on a data-quantity axis.
"""
from __future__ import annotations

import json
import random
import re
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from repair.e3_report import parse_eval_filename

_SIZED_ARM = re.compile(r"^(?P<arm>[a-z_]+?)(?P<size>\d+)$")
BASE_ARM = "base"


def parse_scaling_arm(arm: str) -> tuple[str, int | None]:
    """Split ``fuzzlang4000`` into its arm name and its training-set size."""
    match = _SIZED_ARM.match(arm)
    if not match:
        return arm, None
    return match.group("arm"), int(match.group("size"))


def _load_instances(path: Path) -> list[dict]:
    companion = Path(str(path)[: -len(".json")] + ".instances.jsonl")
    if not companion.is_file():
        return []
    return [
        json.loads(line) for line in companion.read_text().splitlines() if line.strip()
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


def build_scaling_report(
    eval_dir: str | Path, *, bootstrap_samples: int = 2000, seed: int = 20260813,
) -> dict[str, Any]:
    """Assemble the per-cohort curve from the per-(arm, seed, cohort) files."""
    by_cohort: dict[str, dict[str, dict[str | None, list[dict]]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    for path in sorted(Path(eval_dir).glob("*--*.json")):
        arm, arm_seed, cohort = parse_eval_filename(path.name)
        by_cohort[cohort][arm][arm_seed] = _load_instances(path)

    report: dict[str, Any] = {"schema": "fuzzlang.scaling_report.v1", "cohorts": {}}
    for cohort, arms in sorted(by_cohort.items()):
        points: list[dict[str, Any]] = []
        base_rate: float | None = None
        for arm, seeds in arms.items():
            name, size = parse_scaling_arm(arm)
            pooled = [row for rows in seeds.values() for row in rows]
            if not pooled:
                continue
            rate = sum(bool(r.get("compile_ok")) for r in pooled) / len(pooled)
            if size is None:
                if name == BASE_ARM:
                    base_rate = round(rate, 4)
                continue
            per_seed = [
                sum(bool(r.get("compile_ok")) for r in rows) / len(rows)
                for rows in seeds.values() if rows
            ]
            flags = [int(bool(r.get("compile_ok"))) for r in pooled]
            points.append({
                "arm": name,
                "training_records": size,
                "seeds": sorted(s for s in seeds if s is not None) or ["n/a"],
                "instances_per_seed": len(next(iter(seeds.values()))),
                "verified_fix_rate": round(statistics.fmean(per_seed), 4),
                "verified_fix_rate_std": (
                    round(statistics.pstdev(per_seed), 4) if len(per_seed) > 1 else 0.0
                ),
                "verified_fix_rate_ci95": _bootstrap(
                    flags, samples=bootstrap_samples, seed=seed
                ),
                "exact_match_rate": round(
                    sum(bool(r.get("exact_match")) for r in pooled) / len(pooled), 4
                ),
            })

        points.sort(key=lambda point: point["training_records"])
        for index, point in enumerate(points):
            point["delta_vs_previous"] = (
                None if index == 0 else
                round(point["verified_fix_rate"]
                      - points[index - 1]["verified_fix_rate"], 4)
            )
            point["records_added"] = (
                None if index == 0 else
                point["training_records"] - points[index - 1]["training_records"]
            )
        report["cohorts"][cohort] = {"curve": points, "base_rate": base_rate}
    return report


def scaling_rows(report: Mapping[str, Any]) -> list[list[Any]]:
    """CSV rows: one line per cohort and training size."""
    rows: list[list[Any]] = [[
        "cohort", "training_records", "verified_fix_rate", "std", "ci95_low",
        "ci95_high", "exact_match_rate", "delta_vs_previous", "records_added",
        "seeds", "base_rate",
    ]]
    for cohort, block in sorted(report.get("cohorts", {}).items()):
        for point in block["curve"]:
            interval = point.get("verified_fix_rate_ci95") or (None, None)
            rows.append([
                cohort, point["training_records"], point["verified_fix_rate"],
                point["verified_fix_rate_std"], interval[0], interval[1],
                point["exact_match_rate"], point["delta_vs_previous"],
                point["records_added"], "|".join(point["seeds"]),
                block.get("base_rate"),
            ])
    return rows
