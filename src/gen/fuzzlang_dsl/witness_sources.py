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
    """Move selected evidence TUs to the front without dropping sources.

    Witness-builder audits carry one ``witness_source_id``.  The broader
    request builder has no mutated witness but does carry the two real snippet
    ``source_ids`` on which a synthesized lexical Injector is required to
    match.  Direct code-witness requests carry one ``source_id`` and have no
    audit status yet.  All three are valuable replay anchors.
    """
    source_list = tuple(sources)
    by_id = {source.source_id: source for source in source_list}
    requested: list[str] = []
    seen: set[str] = set()
    for row in audit_rows:
        status = row.get("status")
        if status is not None and status != "selected":
            continue
        row_source_ids: list[str] = []
        witness_source_id = row.get("witness_source_id")
        if isinstance(witness_source_id, str) and witness_source_id:
            row_source_ids.append(witness_source_id)
        direct_source_id = row.get("source_id")
        if isinstance(direct_source_id, str) and direct_source_id:
            row_source_ids.append(direct_source_id)
        snippet_source_ids = row.get("source_ids")
        if isinstance(snippet_source_ids, (list, tuple)):
            row_source_ids.extend(
                source_id for source_id in snippet_source_ids
                if isinstance(source_id, str) and source_id
            )
        for source_id in row_source_ids:
            if source_id in seen:
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
