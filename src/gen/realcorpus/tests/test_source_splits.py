from __future__ import annotations

import pytest

from gen.realcorpus.source_splits import (
    SplitPolicy, assign_source_splits, split_manifest, training_source_ids,
)


def _sources(project: str, count: int) -> list[dict]:
    return [
        {"source_id": f"{project}:dir/f{n:04d}.cc", "project": project}
        for n in range(count)
    ]


def _policy(**kwargs) -> SplitPolicy:
    defaults = dict(
        seed=20260808,
        held_out_projects=("abseil", "ffmpeg"),
        eval_fraction=0.15,
    )
    defaults.update(kwargs)
    return SplitPolicy(**defaults)


def test_a_held_out_project_never_produces_a_training_source():
    sources = _sources("llvm", 100) + _sources("abseil", 40)

    assigned = assign_source_splits(sources, _policy())

    llvm = [s for s in assigned if s["project"] == "llvm"]
    abseil = [s for s in assigned if s["project"] == "abseil"]
    assert {s["split"] for s in abseil} == {"heldout_project"}
    assert {s["split"] for s in llvm} == {"train", "eval_unseen_tu"}


def test_eval_fraction_is_approximately_applied_within_each_project():
    """A fixed hash threshold trades an exact count for stability under growth."""
    sources = _sources("llvm", 2000) + _sources("duckdb", 1000)

    assigned = assign_source_splits(sources, _policy(held_out_projects=()))

    for project, total in (("llvm", 2000), ("duckdb", 1000)):
        held = [
            s for s in assigned
            if s["project"] == project and s["split"] == "eval_unseen_tu"
        ]
        assert abs(len(held) / total - 0.15) < 0.03


def test_assignment_is_deterministic_and_seed_dependent():
    sources = _sources("llvm", 200)

    first = assign_source_splits(sources, _policy())
    second = assign_source_splits(sources, _policy())
    other = assign_source_splits(sources, _policy(seed=1))

    assert first == second
    assert first != other
    # A different seed selects different sources; under a fixed threshold the
    # realized count is binomial, so it is close to but not exactly equal.
    counts = [
        sum(1 for s in rows if s["split"] == "eval_unseen_tu")
        for rows in (first, other)
    ]
    assert all(abs(count - 200 * 0.15) < 15 for count in counts)


def test_split_assignment_depends_only_on_the_source_id_not_on_input_order():
    """Re-running after the pool grows must not reshuffle existing sources."""
    sources = _sources("llvm", 100)

    original = {s["source_id"]: s["split"] for s in assign_source_splits(sources, _policy())}
    grown = _sources("llvm", 100) + _sources("llvm2", 50)
    grown = [
        {**s, "project": "llvm"} if s["project"] == "llvm2" else s for s in grown
    ]
    regrown = {s["source_id"]: s["split"] for s in assign_source_splits(grown, _policy())}

    unchanged = sum(
        1 for key, value in original.items() if regrown.get(key) == value
    )
    assert unchanged == len(original)


def test_a_training_source_and_an_eval_source_never_share_an_identity():
    sources = _sources("llvm", 300)

    assigned = assign_source_splits(sources, _policy())

    train = {s["source_id"] for s in assigned if s["split"] == "train"}
    evaluation = {s["source_id"] for s in assigned if s["split"] == "eval_unseen_tu"}
    assert not train & evaluation
    assert len(train) + len(evaluation) == 300


def test_manifest_records_the_policy_and_the_per_project_counts():
    sources = _sources("llvm", 100) + _sources("abseil", 40)

    manifest = split_manifest(assign_source_splits(sources, _policy()), _policy())

    assert manifest["policy"]["seed"] == 20260808
    assert manifest["policy"]["eval_fraction"] == 0.15
    assert manifest["policy"]["held_out_projects"] == ["abseil", "ffmpeg"]
    assert set(manifest["counts"]["llvm"]) == {"train", "eval_unseen_tu"}
    assert sum(manifest["counts"]["llvm"].values()) == 100
    assert manifest["counts"]["abseil"] == {"heldout_project": 40}
    assert manifest["totals"]["train"] == manifest["counts"]["llvm"]["train"]


def test_policy_rejects_a_fraction_that_would_leave_no_evaluation():
    with pytest.raises(ValueError):
        _policy(eval_fraction=0.0)
    with pytest.raises(ValueError):
        _policy(eval_fraction=1.0)


def test_a_tiny_project_still_reserves_at_least_one_evaluation_source():
    sources = _sources("tiny", 3)

    assigned = assign_source_splits(sources, _policy(held_out_projects=()))

    assert sum(1 for s in assigned if s["split"] == "eval_unseen_tu") == 1


def test_training_source_ids_exposes_only_the_generatable_set():
    sources = _sources("llvm", 50) + _sources("abseil", 10)

    ids = training_source_ids(assign_source_splits(sources, _policy()))

    assert all(i.startswith("llvm:") for i in ids)
    assert 0 < len(ids) < 50
