"""Freeze train/eval splits over real source files *before* any generation.

The evaluation columns must be decided while the pool is still just a list of
translation units. If splits are chosen after records exist, whoever chooses
them can see which sources produced good data, and the held-out set stops being
a fair test. Every record therefore inherits its split from its source at
creation time, and a generation run that would emit a record from a held-out
source is a bug rather than a relabelling opportunity.

Two independent holdouts are maintained:

``heldout_project``
    whole projects that contribute no training record at any stage; they are
    the unseen-project evaluation column.
``eval_unseen_tu``
    a fixed fraction of translation units inside each *training* project; they
    are the unseen-file evaluation column for a project the model did train on.

Assignment is a deterministic function of ``(seed, source_id)`` alone, never of
input order or pool size, so growing the pool later cannot reshuffle a source
that has already been used. That stability is why the rule is a *fixed
threshold* on the hash rather than "the lowest-ranked 15%": a rank boundary
moves every time the pool grows, which would silently flip an already-used
source from train to eval. The realized fraction is therefore approximately,
not exactly, ``eval_fraction``.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Sequence

TRAIN = "train"
EVAL_UNSEEN_TU = "eval_unseen_tu"
HELDOUT_PROJECT = "heldout_project"


@dataclass(frozen=True)
class SplitPolicy:
    seed: int
    held_out_projects: tuple[str, ...] = ()
    eval_fraction: float = 0.15

    def __post_init__(self) -> None:
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed must be an integer")
        if not 0.0 < self.eval_fraction < 1.0:
            raise ValueError("eval_fraction must be strictly between 0 and 1")
        object.__setattr__(
            self, "held_out_projects", tuple(self.held_out_projects),
        )

    def to_dict(self) -> dict:
        return {
            "seed": self.seed,
            "held_out_projects": list(self.held_out_projects),
            "eval_fraction": self.eval_fraction,
        }


_HASH_SPACE = 1 << 64


def _rank(source_id: str, seed: int) -> int:
    """A stable pseudo-random rank for one source under one seed."""
    digest = hashlib.sha256(f"{seed}\0{source_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _is_eval(source_id: str, policy: SplitPolicy) -> bool:
    """Threshold test that never moves when the pool grows."""
    return _rank(source_id, policy.seed) < policy.eval_fraction * _HASH_SPACE


def assign_source_splits(
    sources: Iterable[dict], policy: SplitPolicy,
) -> list[dict]:
    """Return each source with its frozen ``split`` field added."""
    rows = [dict(source) for source in sources]
    held_out = set(policy.held_out_projects)

    by_project: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if "source_id" not in row or "project" not in row:
            raise ValueError("each source needs a source_id and a project")
        if row["project"] in held_out:
            row["split"] = HELDOUT_PROJECT
        else:
            by_project[row["project"]].append(row)

    for project_rows in by_project.values():
        for row in project_rows:
            row["split"] = (
                EVAL_UNSEEN_TU if _is_eval(row["source_id"], policy) else TRAIN
            )
        if not any(row["split"] == EVAL_UNSEEN_TU for row in project_rows):
            # A project smaller than roughly 1/eval_fraction sources can draw
            # no evaluation source at all.  Promote its lowest-hash source so
            # every project has an unseen-file column.  This safety net is the
            # one pool-size-dependent decision here, and it stops applying once
            # the project is large enough for the threshold to bite.
            smallest = min(
                project_rows, key=lambda row: _rank(row["source_id"], policy.seed),
            )
            smallest["split"] = EVAL_UNSEEN_TU
    return rows


def split_manifest(assigned: Sequence[dict], policy: SplitPolicy) -> dict:
    """Summarize a frozen assignment for archival next to the source pools."""
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    totals: dict[str, int] = defaultdict(int)
    for row in assigned:
        counts[row["project"]][row["split"]] += 1
        totals[row["split"]] += 1
    return {
        "schema": "fuzzlang.source_split_manifest.v1",
        "policy": policy.to_dict(),
        "counts": {
            project: dict(sorted(split_counts.items(), key=_split_order))
            for project, split_counts in sorted(counts.items())
        },
        "totals": dict(sorted(totals.items(), key=_split_order)),
        "sources": len(assigned),
    }


def _split_order(item: tuple[str, int]) -> tuple[int, str]:
    order = {TRAIN: 0, EVAL_UNSEEN_TU: 1, HELDOUT_PROJECT: 2}
    return order.get(item[0], 9), item[0]


def training_source_ids(assigned: Iterable[dict]) -> frozenset[str]:
    """The only sources a generation run may write training records from."""
    return frozenset(
        row["source_id"] for row in assigned if row["split"] == TRAIN
    )
