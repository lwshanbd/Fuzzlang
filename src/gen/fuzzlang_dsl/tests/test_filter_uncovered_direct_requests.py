from __future__ import annotations

import json

import pytest

from gen.fuzzlang_dsl.filter_uncovered_direct_requests import (
    filter_uncovered_direct_requests,
)


def _direct(name: str, *, evidence: str = "Regression-test trigger evidence") -> dict:
    return {
        "diag_name": name,
        "diag_id": 17,
        "language": "c++",
        "evidence": evidence,
    }


def _witness(name: str) -> dict:
    return {"diag_name": name, "source_path": "clang/lib/Sema/Foo.cpp"}


def test_filter_removes_covered_direct_targets_and_keeps_all_their_witnesses():
    direct, witnesses, manifest = filter_uncovered_direct_requests(
        [_direct("err_covered"), _direct("err_gap")],
        [_witness("err_covered"), _witness("err_gap"), _witness("err_gap")],
        covered_diagnostic_names={"err_covered"},
    )

    assert [row["diag_name"] for row in direct] == ["err_gap"]
    assert [row["diag_name"] for row in witnesses] == ["err_gap", "err_gap"]
    assert manifest == {
        "input_direct_targets": 2,
        "covered_targets_removed": 1,
        "missing_test_evidence_removed": 0,
        "remaining_direct_targets": 1,
        "remaining_witness_requests": 2,
    }


def test_filter_removes_targets_without_prompt_only_test_evidence():
    direct, witnesses, manifest = filter_uncovered_direct_requests(
        [_direct("err_gap", evidence="emission context only")],
        [_witness("err_gap")],
        covered_diagnostic_names=set(),
    )

    assert direct == []
    assert witnesses == []
    assert manifest["missing_test_evidence_removed"] == 1


def test_filter_requires_a_real_source_witness_for_remaining_target():
    with pytest.raises(ValueError, match="no matching real-source witness"):
        filter_uncovered_direct_requests(
            [_direct("err_gap")], [], covered_diagnostic_names=set(),
        )
