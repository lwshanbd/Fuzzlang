"""Build the ordered list of target diagnostics that drives injection.

Targets come from the in-scope error catalog. Each is primed with an exemplar
buggy snippet pulled from the existing dataset (how the diagnostic was triggered
elsewhere) to raise inducibility. Targets are ordered covered-first: a
diagnostic we already have an example for is known-inducible somewhere, so it is
the best bet on real code.
"""
from __future__ import annotations

import json
import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from foundation.diagnostics.catalog import DiagEntry
from gen.realcorpus.features import target_features

# Diagnostic families effectively uninducible by a small semantic edit in
# ordinary code (need inline asm, preprocessor, module/driver context). Sorted
# to the END of the target order so the driver spends attempts where they pay off.
_PATHOLOGICAL_PREFIXES = (
    "err_asm_", "err_pp_", "err_pragma", "err_module", "err_import",
    "err_drv_", "err_fe_", "err_mmap",
)


def _is_pathological(name: str) -> bool:
    return name.startswith(_PATHOLOGICAL_PREFIXES)


@dataclass(frozen=True)
class Target:
    name: str
    message: str
    features: frozenset[str]
    exemplar: Optional[str]       # a buggy snippet that triggered this diagnostic
    covered: bool                 # do we already have an example (exemplar present)?
    observed_in_real: bool = False


def _paired_excerpt(corrected: str, erroneous: str, *, context: int = 4,
                    max_chars: int = 4000) -> str:
    """Compact correct/broken context around the first changed line.

    The old implementation supplied the entire erroneous program.  A paired
    excerpt shows the model the actual error-inducing transformation and keeps
    large exemplars from drowning out the real-code region in the prompt.
    """
    good = corrected.splitlines()
    bad = erroneous.splitlines()
    changes = [op for op in difflib.SequenceMatcher(a=good, b=bad).get_opcodes()
               if op[0] != "equal"]
    if changes:
        _, i1, i2, j1, j2 = changes[0]
        good_part = good[max(0, i1 - context):min(len(good), i2 + context)]
        bad_part = bad[max(0, j1 - context):min(len(bad), j2 + context)]
    else:
        good_part = good[:2 * context + 1]
        bad_part = bad[:2 * context + 1]
    text = ("Correct code:\n" + "\n".join(good_part) +
            "\n\nBroken code:\n" + "\n".join(bad_part))
    return text[:max_chars]


def load_exemplars(dataset_path: Path) -> dict[str, str]:
    """Map diagnostic name -> one compact paired trigger excerpt."""
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
            ex[name] = _paired_excerpt(d["corrected_src"], d["erroneous_src"])
    return ex


def load_observed_names(paths: list[Path]) -> set[str]:
    """Diagnostic names already emitted by prior real-corpus runs.

    Accept both canonical Record JSONL and the flatter run_sweep input format,
    which makes incremental runs able to target only still-missing types.
    """
    names: set[str] = set()
    for path in paths:
        for line in Path(path).read_text().splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            name = d.get("diag_name")
            if not name:
                diags = d.get("diagnostics") or []
                name = diags[0].get("diag_name") if diags else None
            if name:
                names.add(name)
    return names


def load_diagnostic_languages(dataset_path: Path) -> dict[str, set[str]]:
    """Languages in which each diagnostic has a verified exemplar."""
    out: dict[str, set[str]] = {}
    for line in Path(dataset_path).read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        diags = d.get("diagnostics") or []
        name = diags[0].get("diag_name") if diags else None
        language = d.get("language")
        if name and language:
            out.setdefault(name, set()).add(language)
    return out


def build_targets(
    entries: list[DiagEntry],
    out_of_scope: set[str],
    exemplars: dict[str, str],
    *,
    observed_names: Optional[set[str]] = None,
    order_mode: str = "covered-first",
    include_names: Optional[set[str]] = None,
    exclude_components: Optional[set[str]] = None,
) -> list[Target]:
    """Build in-scope targets in a yield- or real-gap-oriented order."""
    if order_mode not in {"covered-first", "real-gap-first", "catalog"}:
        raise ValueError(f"unknown target order: {order_mode}")
    observed_names = observed_names or set()
    targets: list[Target] = []
    for e in entries:
        if e.name in out_of_scope:
            continue
        if exclude_components and e.component in exclude_components:
            continue
        if include_names is not None and e.name not in include_names:
            continue
        exemplar = exemplars.get(e.name)
        targets.append(Target(
            name=e.name, message=e.message or "",
            features=target_features(e.name, e.message or ""),
            exemplar=exemplar, covered=exemplar is not None,
            observed_in_real=e.name in observed_names,
        ))
    order = {t.name: i for i, t in enumerate(targets)}   # catalog order tiebreak
    def priority(t: Target) -> tuple:
        if order_mode == "real-gap-first":
            mode = (1 if t.observed_in_real else 0, 0 if t.covered else 1)
        elif order_mode == "covered-first":
            mode = (0 if t.covered else 1,)
        else:
            mode = ()
        return (
            1 if _is_pathological(t.name) else 0,
            *mode,
            0 if t.features else 1,
            order[t.name],
        )
    targets.sort(key=lambda t: (
        priority(t)
    ))
    return targets
