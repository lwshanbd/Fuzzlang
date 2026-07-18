from __future__ import annotations

from repair.aggregate_eval import slice_rates
from repair.eval.metrics import InstanceResult


def _result(instance_id: str, ok: bool) -> InstanceResult:
    return InstanceResult(
        instance_id=instance_id,
        diag_id=1,
        diag_family="err_x",
        ok=ok,
        turns_used=1,
        tokens_used=10,
        reason="success" if ok else "budget_exhausted",
    )


def test_slice_rates_joins_results_to_generation_metadata():
    results = [_result("a", True), _result("b", False), _result("c", True)]
    metadata = {
        "a": {"generation_label": "exact_target"},
        "b": {"generation_label": "near_miss"},
        "c": {"generation_label": "near_miss"},
    }

    rates = slice_rates(results, metadata, "generation_label")

    assert rates["exact_target"] == {"ok": 1, "n": 1, "rate": 1.0}
    assert rates["near_miss"] == {"ok": 1, "n": 2, "rate": 0.5}


def test_slice_rates_marks_missing_metadata_unknown():
    rates = slice_rates([_result("missing", False)], {}, "cascade_bucket")
    assert rates["__unknown__"] == {"ok": 0, "n": 1, "rate": 0.0}
