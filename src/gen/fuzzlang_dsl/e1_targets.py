"""Fixed stratified diagnostic sample for experiment E1.

E1 compares reusable Injector synthesis against per-record DirectEdit, so its
target list must be decided *before* either arm runs and must not favour either
one.  The sample is therefore drawn only from diagnostics that the canonical
audit already shows to be reachable with a portable Injector: a zero from one
arm then measures the method, not an unreachable diagnostic.

Selection rule (fully determined by ``seed`` and the canonical inventory):

1. keep rows that are in the frozen paper scope, carry at least one strictly
   verified record, and list the requested source language;
2. group them into strata of ``component`` (the error family) crossed with an
   existing-multiplicity band;
3. allocate the sample as evenly as possible over families, then over bands
   inside each family;
4. draw inside each stratum with ``random.Random(seed)`` after sorting by name.
"""
from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class E1Target:
    diag_name: str
    component: str
    language: str
    existing_strict_records: int
    existing_injector_count: int

    @property
    def multiplicity_band(self) -> str:
        return multiplicity_band(self.existing_strict_records)

    @property
    def stratum(self) -> str:
        return f"{self.component}/{self.multiplicity_band}"

    def to_dict(self) -> dict:
        return {
            "diag_name": self.diag_name,
            "component": self.component,
            "language": self.language,
            "existing_strict_records": self.existing_strict_records,
            "existing_injector_count": self.existing_injector_count,
            "multiplicity_band": self.multiplicity_band,
            "stratum": self.stratum,
        }


def multiplicity_band(records: int) -> str:
    """Band a diagnostic by how much verified evidence already exists."""
    if records <= 1:
        return "1"
    if records <= 3:
        return "2-3"
    return "4+"


def _eligible(
    rows: Iterable[dict], *, language: str,
) -> list[E1Target]:
    targets: list[E1Target] = []
    for row in rows:
        if row.get("in_paper_scope") != "true":
            continue
        if language not in str(row.get("languages", "")).split("|"):
            continue
        records = int(row["strict_records"])
        if records < 1:
            continue
        targets.append(E1Target(
            diag_name=row["diag_name"],
            component=row.get("component") or "Unknown",
            language=language,
            existing_strict_records=records,
            existing_injector_count=int(row.get("injector_count", 0)),
        ))
    return targets


def _even_allocation(keys: Sequence[str], size: int) -> dict[str, int]:
    """Spread ``size`` over ``keys`` as evenly as the ordering allows."""
    allocation = {key: size // len(keys) for key in keys}
    for index in range(size % len(keys)):
        allocation[keys[index]] += 1
    return allocation


def select_e1_targets(
    rows: Iterable[dict], *, seed: int, size: int, language: str,
) -> list[E1Target]:
    """Draw the frozen E1 diagnostic sample from a canonical inventory."""
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise ValueError("size must be a positive integer")
    eligible = _eligible(rows, language=language)
    if not eligible:
        raise ValueError("no canonical diagnostic matches the E1 filters")

    by_family: dict[str, list[E1Target]] = defaultdict(list)
    for target in eligible:
        by_family[target.component].append(target)
    families = sorted(by_family)
    rng = random.Random(seed)

    selected: list[E1Target] = []
    shortfall = 0
    for family, quota in _even_allocation(families, size).items():
        drawn = _draw_from_bands(by_family[family], quota, rng)
        shortfall += quota - len(drawn)
        selected.extend(drawn)
    if shortfall:
        # A small family can be exhausted before its quota; refill from the
        # remaining pool so the sample size stays exactly as declared.
        remaining = sorted(
            set(eligible) - set(selected), key=lambda item: item.diag_name,
        )
        rng.shuffle(remaining)
        selected.extend(remaining[:shortfall])
    return sorted(selected, key=lambda item: (item.component, item.diag_name))


def _draw_from_bands(
    family: Sequence[E1Target], quota: int, rng: random.Random,
) -> list[E1Target]:
    by_band: dict[str, list[E1Target]] = defaultdict(list)
    for target in family:
        by_band[target.multiplicity_band].append(target)
    bands = sorted(by_band)
    drawn: list[E1Target] = []
    leftover: list[E1Target] = []
    for band, band_quota in _even_allocation(bands, quota).items():
        candidates = sorted(by_band[band], key=lambda item: item.diag_name)
        rng.shuffle(candidates)
        drawn.extend(candidates[:band_quota])
        leftover.extend(candidates[band_quota:])
    if len(drawn) < quota:
        rng.shuffle(leftover)
        drawn.extend(leftover[:quota - len(drawn)])
    return drawn
