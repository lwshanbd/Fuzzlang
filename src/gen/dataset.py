"""Assemble a usable dataset from raw records: dedup + provenance-isolated splits.

Two steps turn the pile of verified records into a trainable/evaluable dataset:

- **dedup**: drop structurally near-identical records. Two records are the same
  example if they share a diagnostic AND a whitespace-normalized 5-line window
  around the error line — this removes cosmetic-only duplicates while keeping
  genuinely distinct programs (so multiplicity stays honest).
- **split**: partition into train/dev/eval with **provenance isolation** — all
  records sharing a ``provenance.source`` land in the same split (deterministic,
  salted), so no source's examples leak across splits. Mirrors the file-level
  carve in :mod:`real.split_llvm_train_dev`.
"""
from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Iterable

from foundation.ast_hash import text_normalized_hash
from foundation.record import Record, Split


def _dedup_key(rec: Record) -> tuple[str, str]:
    diag = rec.primary_diagnostic
    name = diag.diag_name if diag and diag.diag_name else ""
    line = diag.line if diag and diag.line and diag.line >= 1 else 1
    return name, text_normalized_hash(rec.erroneous_src, line)


def dedup_records(records: Iterable[Record]) -> list[Record]:
    """Drop structurally-duplicate records, keeping the first of each key."""
    seen: set[tuple[str, str]] = set()
    out: list[Record] = []
    for rec in records:
        key = _dedup_key(rec)
        if key not in seen:
            seen.add(key)
            out.append(rec)
    return out


def _bucket(source: str, salt: str, dev_fraction: float, eval_fraction: float) -> Split:
    h = int(hashlib.sha256(f"{salt}|{source}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    if h < eval_fraction:
        return Split.EVAL
    if h < eval_fraction + dev_fraction:
        return Split.DEV
    return Split.TRAIN


def split_records(
    records: Iterable[Record],
    *,
    salt: str,
    dev_fraction: float = 0.1,
    eval_fraction: float = 0.1,
) -> dict[Split, list[Record]]:
    """Partition records into TRAIN/DEV/EVAL, isolated by ``provenance.source``.

    A record's split is a deterministic function of its provenance source, so
    every record from the same source lands in the same split (no leakage). The
    returned records have their ``split`` field set accordingly.
    """
    parts: dict[Split, list[Record]] = {Split.TRAIN: [], Split.DEV: [], Split.EVAL: []}
    for rec in records:
        split = _bucket(rec.provenance.source, salt, dev_fraction, eval_fraction)
        parts[split].append(replace(rec, split=split))
    return parts
