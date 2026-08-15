from __future__ import annotations

from gen.fuzzlang_dsl.injector import FuzzLangInjector
from gen.fuzzlang_dsl.injector_selection import select_canonical_injectors


def _injector(target: str, language: str = "c++", suffix: str = "") -> FuzzLangInjector:
    return FuzzLangInjector(
        target_diag=target,
        target_diag_id=17,
        language=language,
        operation="replace",
        old_patterns=(f"<ID0>{suffix}",),
        new_text="bad",
        left_context=("return",),
        right_context=(";",),
        replacement_parts=(("literal", "bad"),),
        portable=True,
    )


def _manifest(*metrics: dict) -> dict:
    return {
        "schema": "fuzzlang.synthesized_injector_campaign_manifest",
        "schema_version": 1,
        "injectors": list(metrics),
    }


def _metric(injector: FuzzLangInjector, **overrides: int | float) -> dict:
    value = {
        "injector_id": injector.injector_id,
        "target_diag": injector.target_diag,
        "compiled": 10,
        "exact_target": 6,
        "records_emitted": 6,
        "unique_TUs": 4,
        "projects": 1,
        "target_rate": 0.6,
    }
    value.update(overrides)
    return value


def test_selects_primary_and_backup_per_diagnostic_from_campaign_evidence():
    best = _injector("err_same", suffix="best")
    backup = _injector("err_same", suffix="backup")
    weak = _injector("err_same", suffix="weak")
    other = _injector("err_other")

    report = select_canonical_injectors(
        [best, backup, weak, other],
        [_manifest(
            _metric(best, exact_target=8, compiled=10, unique_TUs=5, target_rate=0.8),
            _metric(backup, exact_target=5, compiled=10, unique_TUs=5, target_rate=0.5),
            _metric(weak, exact_target=1, compiled=10, unique_TUs=1, target_rate=0.1),
            _metric(other, exact_target=3, compiled=4, unique_TUs=2, target_rate=0.75),
        )],
        min_exact_target=2,
        min_unique_tus=2,
        min_target_rate=0.25,
        backups_per_diagnostic=1,
    )

    rows = {row["injector_id"]: row for row in report["injectors"]}
    assert rows[best.injector_id]["decision"] == "primary"
    assert rows[backup.injector_id]["decision"] == "backup"
    assert rows[weak.injector_id]["decision"] == "reject"
    assert rows[weak.injector_id]["reasons"] == ["below_min_exact_target", "below_min_unique_tus", "below_min_target_rate"]
    assert rows[other.injector_id]["decision"] == "primary"
    assert report["selected_injector_ids"] == [best.injector_id, backup.injector_id, other.injector_id]


def test_combines_compiler_counts_but_uses_maximum_unique_tus_as_safe_lower_bound():
    injector = _injector("err_target")

    report = select_canonical_injectors(
        [injector],
        [
            _manifest(_metric(injector, compiled=4, exact_target=2, unique_TUs=2, target_rate=0.5)),
            _manifest(_metric(injector, compiled=6, exact_target=3, unique_TUs=3, target_rate=0.5)),
        ],
        min_exact_target=5,
        min_unique_tus=3,
        min_target_rate=0.5,
    )

    row = report["injectors"][0]
    assert row["compiled"] == 10
    assert row["exact_target"] == 5
    assert row["unique_TUs_lower_bound"] == 3
    assert row["target_rate"] == 0.5
    assert row["decision"] == "primary"


def test_rejects_manifest_metrics_for_unknown_or_mismatched_injectors():
    injector = _injector("err_target")
    unknown = _metric(injector)
    unknown["injector_id"] = "fuzzlang-v1-missing"

    try:
        select_canonical_injectors([injector], [_manifest(unknown)])
    except ValueError as error:
        assert "unknown Injector" in str(error)
    else:
        raise AssertionError("unknown campaign Injector must fail")

    mismatch = _metric(injector)
