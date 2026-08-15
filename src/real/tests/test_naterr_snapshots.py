from __future__ import annotations

import pytest

from real.naterr_snapshots import (
    candidates_in_window,
    select_snapshots,
)


def _c(sha: str, date: str) -> dict:
    return {"fix_sha": sha, "commit_date_iso": f"{date}T12:00:00+00:00"}


def test_window_selection_is_inclusive_on_both_edges():
    candidates = [
        _c("a", "2025-01-01"), _c("b", "2025-01-22"), _c("c", "2025-02-12"),
        _c("d", "2025-02-13"),
    ]
    inside = candidates_in_window(candidates, "2025-01-22", window_days=21)

    assert [c["fix_sha"] for c in inside] == ["a", "b", "c"]


def test_snapshots_are_placed_where_they_cover_the_most_candidates():
    # Nine commits in one week, two stragglers a year away. One snapshot on the
    # cluster must come first: each snapshot costs an LLVM configure and build,
    # so the order decides how much a truncated campaign is worth.
    cluster = [_c(f"c{n}", f"2025-06-0{n + 1}") for n in range(9)]
    far = [_c("x", "2024-01-01"), _c("y", "2024-01-02")]

    snapshots = select_snapshots(cluster + far, window_days=21)

    assert snapshots[0]["covers"] == 9
    assert snapshots[0]["date"].startswith("2025-06")
    assert snapshots[1]["covers"] == 2
    assert sum(s["covers"] for s in snapshots) == 11


def test_selection_stops_at_the_requested_snapshot_count():
    candidates = [_c(f"c{n}", f"202{n}-01-01") for n in range(5)]

    snapshots = select_snapshots(candidates, window_days=21, max_snapshots=2)

    assert len(snapshots) == 2
    assert all(s["fix_sha"] and s["date"] for s in snapshots)


def test_selection_is_deterministic_regardless_of_input_order():
    candidates = [_c("a", "2025-01-01"), _c("b", "2025-01-10"),
                  _c("c", "2025-06-01")]

    forward = select_snapshots(candidates, window_days=21)
    reverse = select_snapshots(list(reversed(candidates)), window_days=21)

    assert forward == reverse


def test_a_candidate_without_a_usable_date_is_not_silently_covered():
    with pytest.raises(ValueError):
        select_snapshots([{"fix_sha": "a", "commit_date_iso": "nonsense"}],
                         window_days=21)
