"""Select a small, evidence-backed canonical Injector library.

Campaign manifests are the output of :mod:`run_campaign`: every metric is
backed by clean-parent and exact-typed-diagnostic compiler checks.  This module
does not pretend that repeated campaigns used disjoint source TUs.  It sums
compiler attempts but treats the largest per-campaign unique-TU count as a
safe lower bound until source identities are available in the manifest.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

from gen.fuzzlang_dsl.injector import FuzzLangInjector


_CAMPAIGN_SCHEMA = "fuzzlang.synthesized_injector_campaign_manifest"


def _nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"campaign metric {name} must be a non-negative integer")
    return value


def _positive_int(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _rate(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise ValueError(f"{name} must be between 0 and 1")


def select_canonical_injectors(
    injectors: Sequence[FuzzLangInjector],
    campaign_manifests: Sequence[Mapping[str, Any]],
    *,
    min_exact_target: int = 1,
    min_unique_tus: int = 1,
    min_target_rate: float = 0.0,
    backups_per_diagnostic: int = 1,
) -> dict[str, Any]:
    """Rank compiler-verified Injectors and keep one primary plus backups.

    An Injector is eligible only when its aggregated exact-target evidence,
    conservative cross-source lower bound, and exact-target rate all meet the
    supplied thresholds.  The primary is the eligible candidate with the best
    exact-target rate, then exact-target count, then TU lower bound.  Ties are
    resolved by original Injector input order for reproducibility.
    """
    _positive_int(min_exact_target, "min_exact_target")
    _positive_int(min_unique_tus, "min_unique_tus")
    _rate(min_target_rate, "min_target_rate")
    if isinstance(backups_per_diagnostic, bool) or not isinstance(backups_per_diagnostic, int) or backups_per_diagnostic < 0:
        raise ValueError("backups_per_diagnostic must be a non-negative integer")

    by_id: dict[str, FuzzLangInjector] = {}
    for injector in injectors:
        if not isinstance(injector, FuzzLangInjector):
            raise TypeError("injectors must contain FuzzLangInjector values")
        if injector.injector_id in by_id:
            raise ValueError(f"duplicate Injector ID: {injector.injector_id}")
        by_id[injector.injector_id] = injector

    evidence: dict[str, dict[str, int]] = {
        injector_id: {"compiled": 0, "exact_target": 0, "records_emitted": 0,
                      "unique_TUs_lower_bound": 0, "projects_lower_bound": 0,
                      "campaigns": 0}
        for injector_id in by_id
    }
    for manifest_index, manifest in enumerate(campaign_manifests, 1):
        if manifest.get("schema") != _CAMPAIGN_SCHEMA or manifest.get("schema_version") != 1:
            raise ValueError(f"campaign manifest {manifest_index} has an unsupported schema")
        metrics = manifest.get("injectors")
        if not isinstance(metrics, list):
            raise ValueError(f"campaign manifest {manifest_index} requires an injectors list")
        seen_in_manifest: set[str] = set()
        for metric in metrics:
            if not isinstance(metric, Mapping):
                raise ValueError("campaign Injector metric must be an object")
            injector_id = metric.get("injector_id")
            if not isinstance(injector_id, str) or injector_id not in by_id:
                raise ValueError("campaign metric references an unknown Injector")
            if injector_id in seen_in_manifest:
                raise ValueError("campaign manifest repeats an Injector metric")
            seen_in_manifest.add(injector_id)
            injector = by_id[injector_id]
            if metric.get("target_diag") != injector.target_diag:
                raise ValueError("campaign metric target does not match Injector")
            row = evidence[injector_id]
            row["compiled"] += _nonnegative_int(metric.get("compiled"), "compiled")
            row["exact_target"] += _nonnegative_int(metric.get("exact_target"), "exact_target")
            row["records_emitted"] += _nonnegative_int(metric.get("records_emitted"), "records_emitted")
            row["unique_TUs_lower_bound"] = max(
                row["unique_TUs_lower_bound"],
                _nonnegative_int(metric.get("unique_TUs"), "unique_TUs"),
            )
            row["projects_lower_bound"] = max(
                row["projects_lower_bound"],
                _nonnegative_int(metric.get("projects"), "projects"),
            )
            row["campaigns"] += 1

    rows: list[dict[str, Any]] = []
    eligible_by_target: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for input_order, injector in enumerate(injectors):
        totals = evidence[injector.injector_id]
        rate = totals["exact_target"] / totals["compiled"] if totals["compiled"] else 0.0
        reasons: list[str] = []
        if not injector.portable:
            reasons.append("nonportable")
        if totals["exact_target"] < min_exact_target:
            reasons.append("below_min_exact_target")
        if totals["unique_TUs_lower_bound"] < min_unique_tus:
            reasons.append("below_min_unique_tus")
        if rate < min_target_rate:
            reasons.append("below_min_target_rate")
        row = {
            "injector_id": injector.injector_id,
            "target_diag": injector.target_diag,
            "target_diag_id": injector.target_diag_id,
            "language": injector.language,
            "portable": injector.portable,
            "compiled": totals["compiled"],
            "exact_target": totals["exact_target"],
            "records_emitted": totals["records_emitted"],
            "unique_TUs_lower_bound": totals["unique_TUs_lower_bound"],
            "projects_lower_bound": totals["projects_lower_bound"],
            "campaigns": totals["campaigns"],
            "target_rate": rate,
            "decision": "reject",
            "reasons": reasons,
            "_input_order": input_order,
        }
        rows.append(row)
        if not reasons:
            eligible_by_target[(injector.target_diag, injector.language)].append(row)

    for candidates in eligible_by_target.values():
        candidates.sort(key=lambda row: (
            -row["target_rate"], -row["exact_target"],
            -row["unique_TUs_lower_bound"], row["_input_order"],
        ))
        for rank, row in enumerate(candidates):
            if rank == 0:
                row["decision"] = "primary"
            elif rank <= backups_per_diagnostic:
                row["decision"] = "backup"
            else:
                row["reasons"] = ["lower_ranked_eligible_variant"]

    selected = [row["injector_id"] for row in rows if row["decision"] in {"primary", "backup"}]
    for row in rows:
        row.pop("_input_order")
    return {
        "schema": "fuzzlang.canonical_injector_selection.v1",
        "selection_policy": {
            "min_exact_target": min_exact_target,
            "min_unique_tus": min_unique_tus,
            "min_target_rate": min_target_rate,
            "backups_per_diagnostic": backups_per_diagnostic,
            "unique_tu_aggregation": "maximum per-campaign count; conservative lower bound",
            "ranking": "target_rate, exact_target, unique_TUs_lower_bound, input_order",
        },
        "counts": {
            "input_injectors": len(injectors),
            "primary": sum(row["decision"] == "primary" for row in rows),
            "backup": sum(row["decision"] == "backup" for row in rows),
            "rejected": sum(row["decision"] == "reject" for row in rows),
        },
        "selected_injector_ids": selected,
        "injectors": rows,
    }
