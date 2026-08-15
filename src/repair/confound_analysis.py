"""Ask whether a per-group breakdown measures the group or something else.

E3 reports repair accuracy per project. That number is only about the project
if the projects share the thing that actually drives difficulty -- here, the
diagnostic. They do not: an Injector targets one diagnostic and tends to match
one codebase's idioms, so in the held-out cohort 61 of 68 diagnostics occur in
exactly one project. A per-project rate is then a per-diagnostic-mix rate
wearing a project's name, and "project X is anomalous" is not a claim the data
can carry.

Two functions, deliberately generic:

* :func:`stratum_overlap` says how far the two factors can be separated at all;
* :func:`adjusted_rate` predicts a group from the pooled per-stratum rates, so
  the residual is what is left over for the group itself.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable, Mapping, Sequence


def stratum_overlap(
    instances: Iterable[Mapping[str, Any]],
    *,
    group_key: str = "group",
    stratum_key: str = "stratum",
) -> dict[str, Any]:
    """How much of the sample lets group and stratum be told apart."""
    rows = [
        (str(row[group_key]), str(row[stratum_key])) for row in instances
    ]
    groups_by_stratum: dict[str, set[str]] = defaultdict(set)
    for group, stratum in rows:
        groups_by_stratum[stratum].add(group)
    shared = sum(1 for _, stratum in rows if len(groups_by_stratum[stratum]) > 1)
    per_stratum = Counter(stratum for _, stratum in rows)
    ordered = sorted(per_stratum.values())
    return {
        "instances": len(rows),
        "groups": len({group for group, _ in rows}),
        "strata": len(groups_by_stratum),
        "group_exclusive_strata": sum(
            1 for groups in groups_by_stratum.values() if len(groups) == 1
        ),
        "instances_with_shared_stratum": shared,
        "separable_fraction": round(shared / len(rows), 4) if rows else 0.0,
        "median_instances_per_stratum": (
            ordered[len(ordered) // 2] if ordered else 0
        ),
    }


def adjusted_rate(
    outcomes: Mapping[tuple[str, str], Sequence[int | bool]],
    *,
    group: str,
) -> dict[str, Any]:
    """Predict one group's rate from the pooled rates of the strata it holds.

    ``outcomes`` maps ``(group, stratum)`` to per-instance successes. The
    prediction reweights each stratum's *overall* rate by how much of the group
    that stratum makes up, so ``residual = observed - predicted`` is the part
    the group's identity would have to explain. A residual near zero means the
    breakdown is reporting composition.
    """
    if not any(key[0] == group for key in outcomes):
        raise ValueError(f"no outcomes recorded for group {group!r}")

    stratum_totals: dict[str, list[int]] = defaultdict(list)
    for (_, stratum), values in outcomes.items():
        stratum_totals[stratum].extend(int(bool(value)) for value in values)

    own = [
        (stratum, [int(bool(value)) for value in values])
        for (owner, stratum), values in outcomes.items() if owner == group
    ]
    observed_values = [value for _, values in own for value in values]
    size = len(observed_values)
    predicted = sum(
        len(values) * (sum(stratum_totals[stratum]) / len(stratum_totals[stratum]))
        for stratum, values in own
    ) / size
    observed = sum(observed_values) / size
    return {
        "group": group,
        "instances": size,
        "observed": round(observed, 4),
        "predicted_from_strata": round(predicted, 4),
        "residual": round(observed - predicted, 4),
        "strata_in_group": len(own),
    }
