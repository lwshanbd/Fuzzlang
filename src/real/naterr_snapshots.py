"""Choose the build snapshots a NatErr campaign has to pay for.

A NatErr candidate can only be reproduced against a compile environment close
to its own commit: a file from 2023 does not compile against a 2026 header
tree, and the TableGen-generated ``.inc`` files cannot be recovered without
building at that commit. So each candidate needs a build, and a build is the
expensive unit -- roughly an hour of one node.

One build serves every candidate within a window around it, so the campaign is
a set-cover: place snapshots where they redeem the most candidates. The order
matters as much as the set, because a campaign that is cut short after k builds
should have spent those k on the densest clusters.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Mapping, Sequence


def _commit_date(candidate: Mapping[str, Any]) -> date:
    raw = str(candidate.get("commit_date_iso") or "")[:10]
    try:
        year, month, day = (int(part) for part in raw.split("-"))
        return date(year, month, day)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"candidate {candidate.get('fix_sha')!r} has no usable "
            f"commit_date_iso: {candidate.get('commit_date_iso')!r}"
        ) from exc


def candidates_in_window(
    candidates: Iterable[Mapping[str, Any]],
    snapshot_date: str,
    *,
    window_days: int,
) -> list[Mapping[str, Any]]:
    """Candidates a build at ``snapshot_date`` can serve, edges included."""
    year, month, day = (int(part) for part in str(snapshot_date)[:10].split("-"))
    centre = date(year, month, day)
    return [
        candidate for candidate in candidates
        if abs((_commit_date(candidate) - centre).days) <= window_days
    ]


def select_snapshots(
    candidates: Sequence[Mapping[str, Any]],
    *,
    window_days: int,
    max_snapshots: int | None = None,
) -> list[dict[str, Any]]:
    """Greedy set cover over commit dates, densest cluster first.

    Ties break on the earlier date and then on the SHA, so the plan is
    reproducible and independent of the order candidates arrive in.
    """
    dated = sorted(
        ((_commit_date(c), str(c.get("fix_sha") or "")) for c in candidates),
        key=lambda pair: (pair[0], pair[1]),
    )
    uncovered = list(range(len(dated)))
    snapshots: list[dict[str, Any]] = []
    while uncovered and (max_snapshots is None or len(snapshots) < max_snapshots):
        best_index = None
        best_covered: list[int] = []
        for index in uncovered:
            centre = dated[index][0]
            covered = [
                other for other in uncovered
                if abs((dated[other][0] - centre).days) <= window_days
            ]
            if len(covered) > len(best_covered):
                best_index, best_covered = index, covered
        if best_index is None:
            break
        snapshot_date, fix_sha = dated[best_index]
        snapshots.append({
            "fix_sha": fix_sha,
            "date": snapshot_date.isoformat(),
            "covers": len(best_covered),
        })
        remaining = set(best_covered)
        uncovered = [index for index in uncovered if index not in remaining]
    return snapshots
