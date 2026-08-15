from __future__ import annotations

import pytest

from gen.fuzzlang_dsl.dataset_release import (
    RELEASE_INVARIANTS,
    split_records,
    verify_invariants,
)


def _record(record_id="r0", **overrides):
    detail = {
        "project": "llvm", "source_path": "llvm/lib/A.cpp",
        "target_diag": "err_a", "source_split": "train",
        "injector_id": "fuzzlang-v1-abc", "strategy": "fuzzlang_library_replay",
        "opportunistic_observed_diagnostic": False,
        "primary_matches_target": True,
    }
    detail.update(overrides.pop("detail", {}))
    record = {
        "record_id": record_id,
        "erroneous_src": "int x = ;\n",
        "corrected_src": "int x = 0;\n",
        "language": "c++",
        "split": "train",
        "diagnostics": [{"diag_name": "err_a", "diag_id": 1}],
        "provenance": {"origin": "mutate", "source": "llvm:llvm/lib/A.cpp",
                       "detail": detail},
    }
    record.update(overrides)
    return record


def test_a_clean_record_violates_nothing():
    assert verify_invariants([_record()]) == {}


def test_every_named_invariant_is_actually_checked():
    # The manifest advertises this list; a name with no check behind it would
    # be a release gate that silently passes.
    broken = [
        _record("no_corrected", corrected_src=""),
        _record("same_as_erroneous", corrected_src="int x = ;\n"),
        _record("test_source", detail={"source_path": "clang/test/Sema/a.cpp"}),
        _record("vendored", detail={"source_path": "build/_deps/absl-src/a.cc"}),
        _record("relabelled",
                detail={"opportunistic_observed_diagnostic": True}),
        _record("diag_mismatch", diagnostics=[{"diag_name": "err_b", "diag_id": 2}]),
        _record("no_injector", detail={"injector_id": ""}),
        _record("twice"), _record("twice"),
    ]
    violations = verify_invariants(broken)

    assert set(violations) == set(RELEASE_INVARIANTS)
    assert violations["corrected_src_present"] == ["no_corrected"]
    assert violations["corrected_differs"] == ["same_as_erroneous"]
    assert violations["no_test_source"] == ["test_source"]
    assert violations["no_vendored_source"] == ["vendored"]
    assert violations["target_not_relabelled"] == ["relabelled"]
    assert violations["primary_matches_target"] == ["diag_mismatch"]
    assert violations["injector_recorded"] == ["no_injector"]


def test_duplicate_record_ids_are_a_violation():
    violations = verify_invariants([_record("dup"), _record("dup")])
    assert violations["unique_record_id"] == ["dup"]


def test_records_are_split_on_the_frozen_assignment_not_the_file_they_came_in():
    # The split was frozen before generation; a record carries it in
    # provenance. Trusting the input file instead would let a mis-filed record
    # cross the train/eval boundary silently.
    records = [
        _record("a", detail={"source_split": "train"}),
        _record("b", detail={"source_split": "heldout_project"}),
        _record("c", detail={"source_split": "eval_unseen_tu"}),
    ]
    splits = split_records(records)

    assert sorted(splits) == ["eval_unseen_tu", "heldout_project", "train"]
    assert [r["record_id"] for r in splits["train"]] == ["a"]
    assert splits["train"][0]["split"] == "train"


def test_an_unknown_split_is_an_error_not_a_silent_drop():
    with pytest.raises(ValueError):
        split_records([_record("x", detail={"source_split": "nonsense"})])
