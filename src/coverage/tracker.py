"""Compute diagnostic coverage of a dataset against the catalog.

The headline metric: of the catalog's error diagnostics (the denominator), how
many does the dataset's records actually trigger, and how many examples each
has (multiplicity). The gap list of uncovered / under-covered diagnostics is
what Gen consumes to drive generation.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Optional

from foundation.diagnostics.catalog import Catalog
from foundation.record import Record

# Components whose diagnostics are invocation/environment errors, not
# single-file *code* errors: the source is correct and only the command line /
# build setup is wrong, so they can't form a broken-code/corrected-code pair.
# `--code-only` coverage excludes them so the denominator matches the dataset.
INVOCATION_COMPONENTS = frozenset(
    {"Driver", "Frontend", "Serialization", "InstallAPI", "CrossTU", "Refactoring"}
)


@dataclass
class CoverageReport:
    denominator: frozenset[str]          # all error-diagnostic names in the catalog
    counts: dict[str, int]               # covered name -> example count (denominator only)
    multiplicity_target: int             # examples needed to count as "covered enough"
    component_of: dict[str, str]         # denominator name -> catalog component

    @property
    def total(self) -> int:
        return len(self.denominator)

    @property
    def covered(self) -> int:
        return len(self.counts)

    @property
    def covered_at_target(self) -> int:
        return sum(1 for c in self.counts.values() if c >= self.multiplicity_target)

    @property
    def coverage_fraction(self) -> float:
        return self.covered / self.total if self.total else 0.0

    @property
    def coverage_at_target_fraction(self) -> float:
        return self.covered_at_target / self.total if self.total else 0.0

    def gap_list(self) -> list[tuple[str, int]]:
        """Uncovered + under-covered diagnostics, fewest examples first.

        Each entry is (diag_name, current_count) for names below the target.
        This is the work list handed to Gen.
        """
        gaps = [
            (name, self.counts.get(name, 0))
            for name in self.denominator
            if self.counts.get(name, 0) < self.multiplicity_target
        ]
        gaps.sort(key=lambda nc: (nc[1], nc[0]))
        return gaps

    def by_component(self) -> dict[str, tuple[int, int]]:
        """component -> (covered, total) over the denominator."""
        total = Counter(self.component_of[n] for n in self.denominator)
        covered = Counter(self.component_of[n] for n in self.counts)
        return {c: (covered.get(c, 0), total[c]) for c in total}


def build_report(
    records: Iterable[Record],
    catalog: Catalog,
    multiplicity_target: int = 3,
    exclude_components: Optional[Iterable[str]] = None,
    exclude_names: Optional[Iterable[str]] = None,
) -> CoverageReport:
    excluded = frozenset(exclude_components or ())
    excluded_names = frozenset(exclude_names or ())
    errors = [e for e in catalog.errors()
              if e.component not in excluded and e.name not in excluded_names]
    denominator = frozenset(e.name for e in errors)
    component_of = {e.name: e.component for e in errors}

    counts: Counter[str] = Counter()
    for rec in records:
        diag = rec.primary_diagnostic
        name: Optional[str] = diag.diag_name if diag else None
        if name and name in denominator:
            counts[name] += 1

    return CoverageReport(
        denominator=denominator,
        counts=dict(counts),
        multiplicity_target=multiplicity_target,
        component_of=component_of,
    )
