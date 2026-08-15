from __future__ import annotations

import pytest

from repair.run_build_eval_cohort import stratified_cohort


def _row(record_id: str, project: str, language: str = "c++") -> dict:
    return {
        "record_id": record_id,
        "language": language,
        "provenance": {"source": f"{project}:{record_id}.cc",
                       "detail": {"project": project, "target_diag": "err_x"}},
    }


def _pool() -> list[dict]:
    return (
        [_row(f"ff{n}", "ffmpeg", "c") for n in range(500)]
        + [_row(f"ab{n}", "abseil") for n in range(60)]
        + [_row(f"lv{n}", "leveldb") for n in range(30)]
    )


def test_cohort_is_deterministic_for_a_seed():
    pool = _pool()

    first = stratified_cohort(pool, size=60, seed=7)
    second = stratified_cohort(list(reversed(pool)), size=60, seed=7)

    assert [r["record_id"] for r in first] == [r["record_id"] for r in second]


def test_a_dominant_project_does_not_swamp_the_cohort():
    """Unstratified, 88% of this pool is one C project.

    A cohort that mirrored that would measure language transfer while being
    reported as project transfer.
    """
    cohort = stratified_cohort(_pool(), size=60, seed=1)

    projects = {r["provenance"]["detail"]["project"] for r in cohort}
    ffmpeg = sum(1 for r in cohort if r["provenance"]["detail"]["project"] == "ffmpeg")
    assert projects == {"ffmpeg", "abseil", "leveldb"}
    assert ffmpeg <= len(cohort) // 2


def test_cohort_size_is_respected_and_capped_by_the_pool():
    assert len(stratified_cohort(_pool(), size=60, seed=1)) == 60
    assert len(stratified_cohort(_pool()[:10], size=60, seed=1)) == 10


def test_a_non_positive_size_is_rejected():
    with pytest.raises(ValueError):
        stratified_cohort(_pool(), size=0, seed=1)
