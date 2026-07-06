"""Build the ordered list of target diagnostics that drives injection.

Targets come from the in-scope error catalog. Each is primed with an exemplar
buggy snippet pulled from the existing dataset (how the diagnostic was triggered
elsewhere) to raise inducibility. Targets are ordered covered-first: a
diagnostic we already have an example for is known-inducible somewhere, so it is
the best bet on real code.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from foundation.diagnostics.catalog import DiagEntry
from gen.realcorpus.features import target_features


@dataclass(frozen=True)
class Target:
    name: str
    message: str
    features: frozenset[str]
    exemplar: Optional[str]       # a buggy snippet that triggered this diagnostic
    covered: bool                 # do we already have an example (exemplar present)?


def load_exemplars(dataset_path: Path) -> dict[str, str]:
    """Map diagnostic name -> one erroneous_src from the existing dataset."""
    ex: dict[str, str] = {}
    for line in Path(dataset_path).read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        diags = d.get("diagnostics") or []
        if not diags:
            continue
        name = diags[0].get("diag_name")
        if name and name not in ex:
            ex[name] = d["erroneous_src"]
    return ex


def build_targets(
    entries: list[DiagEntry],
    out_of_scope: set[str],
    exemplars: dict[str, str],
) -> list[Target]:
    """In-scope targets, covered-first then the rest (stable within each group)."""
    targets: list[Target] = []
    for e in entries:
        if e.name in out_of_scope:
            continue
        exemplar = exemplars.get(e.name)
        targets.append(Target(
            name=e.name, message=e.message or "",
            features=target_features(e.name, e.message or ""),
            exemplar=exemplar, covered=exemplar is not None,
        ))
    targets.sort(key=lambda t: 0 if t.covered else 1)  # stable: covered first
    return targets
