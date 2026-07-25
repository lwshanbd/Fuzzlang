from __future__ import annotations

from gen.fuzzlang_dsl.injector import FuzzLangInjector
from gen.fuzzlang_dsl.observed_retarget import select_observed_retargets


def _injector(target: str) -> FuzzLangInjector:
    return FuzzLangInjector(
        target_diag=target,
        target_diag_id=41,
        language="c++",
        operation="replace",
        old_patterns=("<NUM>",),
        new_text="bad",
        left_context=("return",),
        right_context=(";",),
        portable=True,
        replacement_parts=(("literal", "bad"),),
    )


def test_select_observed_retargets_keeps_only_uncovered_catalog_errors():
    original = _injector("err_requested")
    selected, summary = select_observed_retargets(
        (original,),
        (
            {
                "status": "near_miss",
                "injector_id": original.injector_id,
                "observed_diag": "err_new",
            },
            {
                "status": "near_miss",
                "injector_id": original.injector_id,
                "observed_diag": "err_new",
            },
            {
                "status": "near_miss",
                "injector_id": original.injector_id,
                "observed_diag": "err_already_covered",
            },
            {
                "status": "candidate_clean",
                "injector_id": original.injector_id,
                "observed_diag": "err_ignored",
            },
        ),
        catalog_error_names={"err_new", "err_already_covered"},
        covered_names={"err_already_covered"},
    )

    assert len(selected) == 1
    assert selected[0].target_diag == "err_new"
    assert selected[0].target_diag_id is None
    assert selected[0].operation == original.operation
    assert summary == {
        "input_injectors": 1,
        "near_miss_pairs": 3,
        "observed_diagnostic_types": 2,
        "skipped_covered": 1,
        "skipped_non_catalog": 0,
        "retargeted_injectors": 1,
    }
