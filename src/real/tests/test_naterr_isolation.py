from __future__ import annotations

import pytest

from real.naterr_isolation import (
    isolation_report,
    partition_by_isolation,
    training_source_keys,
)


def _training(project: str, path: str) -> dict:
    return {"provenance": {"detail": {"project": project, "source_path": path}}}


def _naterr(project: str, path: str, record_id: str = "n0") -> dict:
    return {
        "record_id": record_id,
        "provenance": {
            "origin": "real",
            "source": f"{project}:{path}",
            "detail": {"project": project, "source_path": path},
        },
    }


def test_training_keys_are_project_qualified_paths():
    keys = training_source_keys([
        _training("llvm", "llvm/lib/A.cpp"),
        _training("duckdb", "src/main.cpp"),
        {"provenance": {"detail": {}}},          # no path -- contributes nothing
    ])
    assert keys == {"llvm:llvm/lib/A.cpp", "duckdb:src/main.cpp"}


def test_a_file_that_was_trained_on_is_dropped_even_at_another_revision():
    # NatErr's value is that the *error* is not ours. It is still worth
    # excluding files the model saw at any revision, so the transfer claim
    # holds at file level and not only at error level.
    kept, dropped = partition_by_isolation(
        [_naterr("llvm", "llvm/lib/A.cpp", "seen"),
         _naterr("llvm", "llvm/lib/B.cpp", "unseen")],
        training_source_keys([_training("llvm", "llvm/lib/A.cpp")]),
    )

    assert [r["record_id"] for r in kept] == ["unseen"]
    assert [(r["record_id"], reason) for r, reason in dropped] == [
        ("seen", "trained_source_file")
    ]


def test_same_path_in_a_different_project_is_not_a_collision():
    kept, dropped = partition_by_isolation(
        [_naterr("llvm", "src/main.cpp")],
        training_source_keys([_training("duckdb", "src/main.cpp")]),
    )
    assert len(kept) == 1 and not dropped


def test_report_states_both_cohorts_and_the_overlap_rate():
    report = isolation_report(
        [_naterr("llvm", "a.cpp", "r0"), _naterr("llvm", "b.cpp", "r1"),
         _naterr("llvm", "c.cpp", "r2")],
        training_source_keys([_training("llvm", "a.cpp")]),
    )

    assert report["naterr_records"] == 3
    assert report["isolated_records"] == 2
    assert report["dropped_records"] == 1
    assert report["overlap_rate"] == pytest.approx(1 / 3, abs=1e-4)
    assert report["dropped_by_reason"] == {"trained_source_file": 1}
