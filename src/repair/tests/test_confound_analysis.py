from __future__ import annotations

import pytest

from repair.confound_analysis import (
    adjusted_rate,
    stratum_overlap,
)


def _instances(rows):
    """rows: (group, stratum, n_instances)."""
    return [
        {"group": group, "stratum": stratum, "record_id": f"{group}-{stratum}-{n}"}
        for group, stratum, count in rows for n in range(count)
    ]


def test_overlap_reports_how_far_the_two_factors_can_be_separated():
    # Every stratum sits in exactly one group: the two factors are perfectly
    # confounded and no per-group number can be attributed to the group.
    confounded = stratum_overlap(_instances([("a", "x", 3), ("b", "y", 3)]))
    assert confounded["strata"] == 2
    assert confounded["group_exclusive_strata"] == 2
    assert confounded["instances_with_shared_stratum"] == 0
    assert confounded["separable_fraction"] == 0.0

    crossed = stratum_overlap(_instances([("a", "x", 3), ("b", "x", 3)]))
    assert crossed["group_exclusive_strata"] == 0
    assert crossed["separable_fraction"] == 1.0


def test_adjusted_rate_predicts_a_group_from_its_stratum_mix():
    # Group "a" looks better only because it holds more of the easy stratum.
    outcomes = {
        ("a", "easy"): [1, 1, 1, 1], ("a", "hard"): [0],
        ("b", "easy"): [1], ("b", "hard"): [0, 0, 0, 0],
    }
    result = adjusted_rate(outcomes, group="a")

    assert result["observed"] == pytest.approx(0.8)
    # Pooled stratum rates: easy 5/5 = 1.0, hard 0/5 = 0.0; "a" is 4/5 easy.
    assert result["predicted_from_strata"] == pytest.approx(0.8)
    assert result["residual"] == pytest.approx(0.0)


def test_a_residual_survives_when_the_group_really_does_differ():
    outcomes = {
        ("a", "shared"): [1, 1, 1, 1], ("b", "shared"): [0, 0, 0, 0],
    }
    result = adjusted_rate(outcomes, group="a")

    assert result["observed"] == 1.0
    assert result["predicted_from_strata"] == pytest.approx(0.5)
    assert result["residual"] == pytest.approx(0.5)


def test_an_unseen_group_is_an_error_not_a_zero():
    with pytest.raises(ValueError):
        adjusted_rate({("a", "x"): [1]}, group="missing")
