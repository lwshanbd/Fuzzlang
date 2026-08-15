"""Isolate the NatErr evaluation set from everything the model trained on.

NatErr answers one objection: every other FuzzLang result evaluates the model
on errors FuzzLang itself created, so a reviewer can ask whether the model
learned to repair *compilation errors* or merely learned this generator. NatErr
takes errors that developers made and the compiler recorded, which FuzzLang did
not create.

That argument only holds if the evaluation set is genuinely apart from
training. LLVM is the largest single contributor to the training corpus, and it
is also the only project whose history yields fix-build commits in useful
quantity, so the two overlap by default. Isolation here is at **file** level: a
NatErr record is dropped when the model was trained on *any* revision of the
same file in the same project. The error would still be new, but the
surrounding code would not, and the weaker claim is not worth defending.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping

DROP_TRAINED_SOURCE = "trained_source_file"


def _source_key(detail: Mapping[str, Any]) -> str | None:
    project = detail.get("project")
    source_path = detail.get("source_path")
    if not project or not source_path:
        return None
    return f"{project}:{str(source_path).replace(chr(92), '/')}"


def training_source_keys(records: Iterable[Mapping[str, Any]]) -> set[str]:
    """Project-qualified source paths the model was trained on."""
    keys: set[str] = set()
    for record in records:
        detail = (record.get("provenance") or {}).get("detail") or {}
        key = _source_key(detail)
        if key:
            keys.add(key)
    return keys


def partition_by_isolation(
    naterr_records: Iterable[Mapping[str, Any]],
    training_keys: set[str],
) -> tuple[list[Mapping[str, Any]], list[tuple[Mapping[str, Any], str]]]:
    """Split NatErr records into the isolated set and the dropped set."""
    kept: list[Mapping[str, Any]] = []
    dropped: list[tuple[Mapping[str, Any], str]] = []
    for record in naterr_records:
        provenance = record.get("provenance") or {}
        detail = provenance.get("detail") or {}
        key = _source_key(detail) or provenance.get("source")
        if key in training_keys:
            dropped.append((record, DROP_TRAINED_SOURCE))
            continue
        kept.append(record)
    return kept, dropped


def isolation_report(
    naterr_records: Iterable[Mapping[str, Any]],
    training_keys: set[str],
) -> dict[str, Any]:
    """Counts a release manifest can quote, including the overlap rate."""
    records = list(naterr_records)
    kept, dropped = partition_by_isolation(records, training_keys)
    reasons = Counter(reason for _, reason in dropped)
    return {
        "naterr_records": len(records),
        "isolated_records": len(kept),
        "dropped_records": len(dropped),
        "overlap_rate": (
            round(len(dropped) / len(records), 4) if records else 0.0
        ),
        "dropped_by_reason": dict(sorted(reasons.items())),
        "training_source_files": len(training_keys),
        "isolation_level": "file",
    }
