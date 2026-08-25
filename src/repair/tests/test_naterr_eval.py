from __future__ import annotations

import pytest

from repair.naterr_eval import (
    diagnostic_present,
    score_repair,
    summarize_naterr,
)


class _Result:
    def __init__(self, ok, stderr=""):
        self.ok = ok
        self.raw_stderr = stderr


def test_a_diagnostic_is_present_only_when_its_own_id_is_reported():
    stderr = "a.cpp:3:9: error: no member named 'x'\nDiagID: 4242\n1 error generated.\n"
    assert diagnostic_present(stderr, 4242) is True
    # 424 must not match inside 4242, and 42420 must not either.
    assert diagnostic_present(stderr, 424) is False
    assert diagnostic_present(stderr, 42420) is False
    assert diagnostic_present("", 4242) is False


def test_a_clean_compile_counts_as_eliminating_the_target():
    assert score_repair(_Result(True), target_diag_id=7)["target_eliminated"] is True
    assert score_repair(_Result(True), target_diag_id=7)["compiles_clean"] is True


def test_the_target_surviving_is_not_a_repair():
    out = score_repair(
        _Result(False, "error: bad\nDiagID: 7\n"), target_diag_id=7,
    )
    assert out["target_eliminated"] is False
    assert out["compiles_clean"] is False


def test_a_different_error_remaining_still_counts_as_eliminating_the_target():
    # The reference fix for these records often will not compile either, because
    # the surrounding tree has moved on. Requiring a fully clean build would
    # score every one of them zero and measure the tree, not the model. What is
    # attributable to the model is whether the error it was shown is gone.
    out = score_repair(
        _Result(False, "error: unrelated\nDiagID: 99\n"), target_diag_id=7,
    )
    assert out["target_eliminated"] is True
    assert out["compiles_clean"] is False


def test_summary_separates_eliminated_from_cleanly_compiling_and_degenerate():
    rows = [
        {"parse_ok": True, "target_eliminated": True, "compiles_clean": False,
         "degenerate": False},
        {"parse_ok": True, "target_eliminated": True, "compiles_clean": True,
         "degenerate": True},
        {"parse_ok": True, "target_eliminated": False, "compiles_clean": False,
         "degenerate": False},
        {"parse_ok": False, "target_eliminated": False, "compiles_clean": False,
         "degenerate": False},
    ]
    s = summarize_naterr(rows)

    assert s["n"] == 4
    assert s["parse_ok"] == 3
    assert s["target_eliminated"] == 2
    assert s["compiles_clean"] == 1
    # Deleting the offending code also eliminates the diagnostic, so the headline
    # rate must exclude it rather than mention it in a footnote.
    assert s["degenerate"] == 1
    assert s["target_eliminated_nondegenerate"] == 1
    assert s["target_eliminated_rate"] == pytest.approx(0.5)
    assert s["target_eliminated_nondegenerate_rate"] == pytest.approx(0.25)


def test_summary_refuses_an_empty_set():
    with pytest.raises(ValueError):
        summarize_naterr([])


def test_the_developers_own_fix_is_what_separates_a_real_error_from_drift():
    # Reproducing an old file against a new tree invents errors nobody made:
    # a header deleted years later, a member that has since moved. The test is
    # whether the developer's commit addressed *this* diagnostic. If applying
    # their fix leaves it firing, they were not fixing it and we should not
    # score a model on it.
    from repair.naterr_eval import is_real_developer_error

    assert is_real_developer_error(
        _Result(False, "error: other\nDiagID: 99\n"), target_diag_id=7) is True
    assert is_real_developer_error(_Result(True), target_diag_id=7) is True
    assert is_real_developer_error(
        _Result(False, "error: same\nDiagID: 7\n"), target_diag_id=7) is False


def test_a_masked_error_is_only_usable_when_it_lies_in_the_window_shown():
    # Stage 2 records the *first* diagnostic, which is often a drift artifact
    # masking the real one. Retargeting to the error the developer's fix
    # actually removed recovers those instances -- but only if it sits inside
    # the source window the model is given. Outside it, the model is being
    # asked to repair code it cannot see.
    from repair.naterr_eval import usable_retarget

    assert usable_retarget(
        removed_diag_lines={7: 42}, window_first_line=30, window_last_line=60
    ) == 7
    assert usable_retarget(
        removed_diag_lines={7: 400}, window_first_line=30, window_last_line=60
    ) is None
    # Several candidates: take the one nearest the middle of the window.
    assert usable_retarget(
        removed_diag_lines={7: 31, 9: 45}, window_first_line=30, window_last_line=60
    ) == 9
    assert usable_retarget(
        removed_diag_lines={}, window_first_line=30, window_last_line=60
    ) is None
