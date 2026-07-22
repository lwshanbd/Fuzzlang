"""Prioritize clean sources that produced compiler-validated synthesis witnesses."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from gen.realcorpus.clean_source_pool import CleanSourceTU


@dataclass(frozen=True)
class WitnessSourceOrder:
    """A source pool reordered so each witness is reached early in replay."""

    sources: tuple[CleanSourceTU, ...]
    prioritized_source_ids: tuple[str, ...]
    missing_witness_source_ids: tuple[str, ...]


def prioritize_witness_sources(
    sources: Iterable[CleanSourceTU],
    audit_rows: Iterable[Mapping[str, object]],
) -> WitnessSourceOrder:
    """Move selected-request witness TUs to the front without dropping sources."""
    source_list = tuple(sources)
    by_id = {source.source_id: source for source in source_list}
    requested: list[str] = []
    seen: set[str] = set()
    for row in audit_rows:
        if row.get("status") != "selected":
            continue
        source_id = row.get("witness_source_id")
        if not isinstance(source_id, str) or not source_id or source_id in seen:
            continue
        seen.add(source_id)
        requested.append(source_id)

    prioritized = tuple(source_id for source_id in requested if source_id in by_id)
    missing = tuple(source_id for source_id in requested if source_id not in by_id)
    prioritized_set = set(prioritized)
    ordered = tuple(by_id[source_id] for source_id in prioritized) + tuple(
        source for source in source_list if source.source_id not in prioritized_set
    )
    return WitnessSourceOrder(ordered, prioritized, missing)
