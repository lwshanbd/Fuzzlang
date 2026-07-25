"""Derive candidate Injectors from compiler-observed near-miss diagnostics."""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import Iterable, Mapping, Sequence

from gen.fuzzlang_dsl.injector import FuzzLangInjector


def select_observed_retargets(
    injectors: Sequence[FuzzLangInjector],
    rejections: Iterable[Mapping[str, object]],
    *,
    catalog_error_names: set[str] | frozenset[str],
    covered_names: set[str] | frozenset[str],
) -> tuple[tuple[FuzzLangInjector, ...], dict[str, int]]:
    """Retarget portable Injectors only to compiler-observed uncovered errors.

    A near miss is never silently accepted as a dataset record.  Instead, this
    produces a new Injector whose target is the compiler's observed primary
    diagnostic.  The caller must replay it through the normal exact-target
    compiler gate before it contributes coverage.
    """
    by_id: dict[str, FuzzLangInjector] = {}
    for injector in injectors:
        if not isinstance(injector, FuzzLangInjector):
            raise TypeError("injectors must contain FuzzLangInjector objects")
        if injector.injector_id in by_id:
            raise ValueError(f"duplicate Injector ID: {injector.injector_id}")
        by_id[injector.injector_id] = injector

    observations: Counter[tuple[str, str]] = Counter()
    for rejection in rejections:
        if rejection.get("status") != "near_miss":
            continue
        injector_id = rejection.get("injector_id")
        observed = rejection.get("observed_diag")
        if (
            isinstance(injector_id, str)
            and injector_id in by_id
            and isinstance(observed, str)
            and observed
        ):
            observations[(injector_id, observed)] += 1

    selected: list[FuzzLangInjector] = []
    seen: set[str] = set()
    skipped_covered = 0
    skipped_non_catalog = 0
    for (injector_id, observed), _count in sorted(observations.items()):
        if observed in covered_names:
            skipped_covered += 1
            continue
        if observed not in catalog_error_names:
            skipped_non_catalog += 1
            continue
        original = by_id[injector_id]
        if original.target_diag == observed:
            continue
        # A TableGen file has no stable numeric ID.  The replay verifier still
        # requires an exact diagnostic name; omitting a stale prior ID is the
        # only sound choice until the compiler emits the retargeted record.
        retargeted = replace(
            original,
            target_diag=observed,
            target_diag_id=None,
        )
        if retargeted.injector_id in seen:
            continue
        seen.add(retargeted.injector_id)
        selected.append(retargeted)

    summary = {
        "input_injectors": len(injectors),
        "near_miss_pairs": sum(observations.values()),
        "observed_diagnostic_types": len({
            observed for _injector_id, observed in observations
        }),
        "skipped_covered": skipped_covered,
        "skipped_non_catalog": skipped_non_catalog,
        "retargeted_injectors": len(selected),
    }
    return tuple(selected), summary
