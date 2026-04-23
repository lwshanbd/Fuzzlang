"""Tests for eval.metrics: fix_rate, per-family breakdown, bootstrap CI."""
from __future__ import annotations

from experiments.eval.metrics import (
    InstanceResult,
    bootstrap_ci,
    diag_family_from_name,
    macro_avg_by_family,
    per_family_rate,
    stratified_bootstrap_ci,
    summarize,
    verified_fix_rate,
)


def _r(instance_id: str, ok: bool, family: str | None = "err_expected") -> InstanceResult:
    return InstanceResult(
        instance_id=instance_id, diag_id=1, diag_family=family,
        ok=ok, turns_used=1 if ok else 5, tokens_used=200,
        reason="success" if ok else "budget_exhausted",
    )


def test_verified_fix_rate_basic():
    rs = [_r("a", True), _r("b", True), _r("c", False), _r("d", False)]
    assert abs(verified_fix_rate(rs) - 0.5) < 1e-9


def test_per_family_separates_by_family():
    rs = [
        _r("a", True, "err_expected"),
        _r("b", False, "err_expected"),
        _r("c", True, "err_template"),
    ]
    out = per_family_rate(rs)
    assert out["err_expected"] == (1, 2, 0.5)
    assert out["err_template"] == (1, 1, 1.0)


def test_macro_avg_weights_families_equally():
    # One family with 1/2 = 0.5, another with 1/1 = 1.0. Macro = mean = 0.75.
    rs = [
        _r("a", True, "err_expected"),
        _r("b", False, "err_expected"),
        _r("c", True, "err_template"),
    ]
    assert abs(macro_avg_by_family(rs) - 0.75) < 1e-9
    # Micro is 2/3 ≈ 0.667 — different by design from macro.
    assert abs(verified_fix_rate(rs) - (2 / 3)) < 1e-9


def test_diag_family_from_name():
    assert diag_family_from_name("err_expected_semi") == "err_expected"
    assert diag_family_from_name("err_undeclared_var") == "err_undeclared"
    # 2-token names kept whole.
    assert diag_family_from_name("err_semi") == "err_semi"
    assert diag_family_from_name(None) is None


def test_bootstrap_ci_on_small_sample_is_wide_but_correct():
    rs = [_r("a", True), _r("b", True), _r("c", False), _r("d", False)]
    point, lo, hi = bootstrap_ci(rs, n_resamples=2000, seed=42)
    assert abs(point - 0.5) < 1e-9
    assert 0.0 <= lo < point < hi <= 1.0


def test_bootstrap_ci_is_reproducible_given_seed():
    rs = [_r(str(i), i % 3 == 0) for i in range(30)]
    p1, lo1, hi1 = bootstrap_ci(rs, n_resamples=1000, seed=17)
    p2, lo2, hi2 = bootstrap_ci(rs, n_resamples=1000, seed=17)
    assert (p1, lo1, hi1) == (p2, lo2, hi2)


def test_stratified_bootstrap_preserves_family_proportions_in_resamples():
    # Small sanity check: with a single family, stratified == standard.
    rs = [_r(str(i), i % 2 == 0, "err_x") for i in range(20)]
    p_std, _, _ = bootstrap_ci(rs, n_resamples=1000, seed=3)
    p_str, _, _ = stratified_bootstrap_ci(rs, n_resamples=1000, seed=3)
    assert abs(p_std - p_str) < 1e-9


def test_summarize_returns_complete_table_row():
    rs = [_r(str(i), i % 3 == 0) for i in range(12)]
    out = summarize(rs, n_resamples=500, seed=1)
    assert out["n"] == 12
    assert 0.0 <= out["verified_fix_rate_micro"] <= 1.0
    lo, hi = out["verified_fix_rate_micro_ci95"]
    assert 0.0 <= lo <= out["verified_fix_rate_micro"] <= hi <= 1.0
    assert out["total_output_tokens"] == 12 * 200
    assert out["avg_turns"] > 0
    assert "per_family" in out
