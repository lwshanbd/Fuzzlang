from __future__ import annotations

import pytest

from gen.fuzzlang_dsl.e1_targets import (
    E1Target, multiplicity_band, select_e1_targets,
)


def _row(name, component, records, language="c++", paper=True) -> dict[str, str]:
    return {
        "diag_name": name,
        "component": component,
        "in_paper_scope": "true" if paper else "false",
        "new_vs_base": "false",
        "strict_records": str(records),
        "source_tus": str(records),
        "injector_count": "1",
        "languages": language,
        "projects": "llvm",
        "strategies": "gemma_code_witness_injector_replay",
        "campaign_count": "1",
        "injector_ids": "fuzzlang-v1-aaaa",
    }


def _population(count: int = 60) -> list[dict[str, str]]:
    components = ("Sema", "Parse", "Lex")
    return [
        _row(f"err_{component.lower()}_{number:03d}", component, 1 + number % 5)
        for component in components
        for number in range(count // len(components))
    ]


def test_multiplicity_band_partitions_by_existing_evidence():
    assert multiplicity_band(1) == "1"
    assert multiplicity_band(2) == "2-3"
    assert multiplicity_band(3) == "2-3"
    assert multiplicity_band(4) == "4+"


def test_selection_is_deterministic_for_a_fixed_seed():
    rows = _population()

    first = select_e1_targets(rows, seed=20260807, size=12, language="c++")
    second = select_e1_targets(rows, seed=20260807, size=12, language="c++")
    other = select_e1_targets(rows, seed=1, size=12, language="c++")

    assert [target.diag_name for target in first] == [
        target.diag_name for target in second
    ]
    assert [target.diag_name for target in first] != [
        target.diag_name for target in other
    ]
    assert all(isinstance(target, E1Target) for target in first)


def test_selection_spans_every_available_error_family():
    rows = _population()

    targets = select_e1_targets(rows, seed=7, size=12, language="c++")

    assert len(targets) == 12
    assert {target.component for target in targets} == {"Sema", "Parse", "Lex"}
    # Even allocation over families keeps one component from dominating.
    counts = {
        component: sum(1 for t in targets if t.component == component)
        for component in ("Sema", "Parse", "Lex")
    }
    assert max(counts.values()) - min(counts.values()) <= 1


def test_selection_covers_low_and_high_multiplicity_strata():
    rows = _population()

    targets = select_e1_targets(rows, seed=11, size=18, language="c++")

    assert {target.multiplicity_band for target in targets} == {"1", "2-3", "4+"}


def test_selection_only_uses_covered_paper_scope_diagnostics_of_one_language():
    rows = [
        _row("err_in_scope", "Sema", 2),
        _row("err_out_of_scope", "Sema", 2, paper=False),
        _row("err_other_language", "Sema", 2, language="c"),
    ]

    targets = select_e1_targets(rows, seed=3, size=5, language="c++")

    assert [target.diag_name for target in targets] == ["err_in_scope"]


def test_selection_rejects_an_impossible_request():
    with pytest.raises(ValueError):
        select_e1_targets(_population(), seed=1, size=0, language="c++")


def test_targets_serialize_with_their_selection_stratum():
    rows = [_row("err_in_scope", "Sema", 4)]

    target = select_e1_targets(rows, seed=1, size=1, language="c++")[0]

    assert target.to_dict() == {
        "diag_name": "err_in_scope",
        "component": "Sema",
        "language": "c++",
        "existing_strict_records": 4,
        "existing_injector_count": 1,
        "multiplicity_band": "4+",
        "stratum": "Sema/4+",
    }
