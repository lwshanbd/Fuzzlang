from __future__ import annotations

import pytest

from foundation.types import DiagInfo
from gen.fuzzlang_dsl.injector import FuzzLangInjector
from gen.fuzzlang_dsl.library_replay import (
    DiagnosticBudget, ReplayCaps, load_injector_library,
    order_library_for_coverage, replay_library,
)

CLEAN = "int f() { return 0; }\nint g() { return 1; }\n"


def _injector(target="err_target", diag_id=17, literal="BROKEN", portable=True):
    return FuzzLangInjector(
        target_diag=target,
        target_diag_id=diag_id,
        language="c++",
        operation="replace",
        old_patterns=("<NUM>",),
        new_text=literal,
        left_context=("return",),
        right_context=(";",),
        replacement_parts=(("literal", literal),),
        portable=portable,
    )


def _source(source_id="llvm:a.cc", split="train", project="llvm"):
    return {
        "source_id": source_id,
        "project": project,
        "source_path": source_id.split(":", 1)[1],
        "language": "c++",
        "compile_cmd": ["__CLANG__", "-std=c++23", "__SRC__"],
        "corrected_src": CLEAN,
        "split": split,
    }


class _Verifier:
    def __init__(self, marker="BROKEN", name="err_target", diag_id=17):
        self.marker, self.name, self.diag_id, self.calls = marker, name, diag_id, 0

    def verify(self, source, compile_cmd, *, logical_path):
        self.calls += 1
        if self.marker in source:
            return _Result(False, DiagInfo(
                diag_id=self.diag_id, diag_name=self.name, diag_msg="m",
                file=logical_path, line=1, col=1, start_byte=0, end_byte=1,
                span_snippet="x",
            ))
        return _Result(True, None)


class _Result:
    def __init__(self, ok, diag):
        self.ok, self.diag = ok, diag


def test_replay_accepts_only_exact_target_records_and_makes_no_model_call():
    result = replay_library(
        [_injector()], [_source(), _source("llvm:b.cc")], _Verifier(),
        caps=ReplayCaps(),
    )

    assert len(result.records) == 2
    assert result.budget.model_calls == 0
    assert result.budget.output_tokens == 0
    assert all(
        r.provenance.detail["strategy"] == "fuzzlang_library_replay"
        for r in result.records
    )
    assert all(r.corrected_src == CLEAN for r in result.records)


def test_replay_refuses_to_write_a_training_record_from_a_held_out_source():
    """The split guard must fail loudly, never silently relabel."""
    with pytest.raises(ValueError, match="held-out"):
        replay_library(
            [_injector()], [_source(split="eval_unseen_tu")], _Verifier(),
            caps=ReplayCaps(),
        )
    with pytest.raises(ValueError, match="held-out"):
        replay_library(
            [_injector()], [_source(split="heldout_project")], _Verifier(),
            caps=ReplayCaps(),
        )


def test_an_evaluation_run_may_target_a_named_split_explicitly():
    result = replay_library(
        [_injector()], [_source(split="eval_unseen_tu")], _Verifier(),
        caps=ReplayCaps(), split="eval_unseen_tu",
    )

    assert len(result.records) == 1
    assert result.records[0].split.value == "eval"


def test_a_wrong_diagnostic_or_clean_mutant_is_rejected_with_a_reason():
    wrong = replay_library(
        [_injector()], [_source()], _Verifier(name="err_other"), caps=ReplayCaps(),
    )
    clean = replay_library(
        [_injector(literal="1")], [_source()], _Verifier(), caps=ReplayCaps(),
    )

    assert wrong.records == [] and clean.records == []
    assert wrong.rejections == {"wrong_primary_diagnostic": 1}
    assert clean.rejections == {"mutant_compiles_clean": 1}


def test_caps_stop_one_injector_or_one_file_from_flooding_the_dataset():
    injectors = [_injector(literal=f"BROKEN{n}") for n in range(5)]
    sources = [_source(f"llvm:f{n}.cc") for n in range(5)]

    capped = replay_library(
        injectors, sources, _Verifier(),
        caps=ReplayCaps(max_records_per_source=2, max_records_per_diagnostic=6),
    )

    per_source: dict[str, int] = {}
    for record in capped.records:
        per_source[record.provenance.source] = per_source.get(record.provenance.source, 0) + 1
    assert max(per_source.values()) <= 2
    assert len(capped.records) <= 6


def test_reach_reports_per_injector_and_per_project_spread():
    injectors = [_injector()]
    sources = [
        _source("llvm:a.cc"), _source("llvm:b.cc"),
        _source("duckdb:c.cc", project="duckdb"),
    ]

    result = replay_library(injectors, sources, _Verifier(), caps=ReplayCaps())

    reach = result.reach[injectors[0].injector_id]
    assert reach["sources"] == 3
    assert reach["projects"] == ["duckdb", "llvm"]
    assert result.summary()["diagnostics"] == 1
    assert result.summary()["projects"] == 2
    assert result.summary()["zero_model_calls"] is True


def test_library_loading_keeps_portable_injectors_and_deduplicates(tmp_path):
    portable, private = _injector(), _injector(target="err_other", portable=False)
    first, second = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    first.write_text(portable.to_json() + "\n" + private.to_json() + "\n")
    second.write_text(portable.to_json() + "\n")

    library = load_injector_library([first, second])

    assert [i.injector_id for i in library] == [portable.injector_id]


def test_library_is_ordered_round_robin_over_target_diagnostics():
    """Per-source verification budget is scarce, so spend it on breadth.

    In file order a source's 24 compiles can all go to Injectors targeting the
    same few diagnostics; round-robin spends them on 24 different targets.
    """
    library = [
        _injector(target="err_a"), _injector(target="err_a"),
        _injector(target="err_a"), _injector(target="err_b"),
        _injector(target="err_c"),
    ]

    ordered = order_library_for_coverage(library)

    assert [i.target_diag for i in ordered[:3]] == ["err_a", "err_b", "err_c"]
    assert len(ordered) == len(library)
    assert {i.injector_id for i in ordered} == {i.injector_id for i in library}


def test_ordering_is_deterministic():
    library = [_injector(target=f"err_{n}", literal=f"X{n}") for n in range(6)]

    assert [i.injector_id for i in order_library_for_coverage(library)] == [
        i.injector_id for i in order_library_for_coverage(list(reversed(library)))
    ]


def test_a_shared_diagnostic_budget_caps_across_concurrent_shards():
    """Sharded runs must not each spend the full per-diagnostic cap."""
    budget = DiagnosticBudget(cap=2)
    first = replay_library(
        [_injector()], [_source("llvm:a.cc"), _source("llvm:b.cc")], _Verifier(),
        caps=ReplayCaps(), diagnostic_budget=budget,
    )
    second = replay_library(
        [_injector()], [_source("llvm:c.cc"), _source("llvm:d.cc")], _Verifier(),
        caps=ReplayCaps(), diagnostic_budget=budget,
    )

    assert len(first.records) + len(second.records) == 2
    assert second.rejections.get("diagnostic_budget_exhausted", 0) >= 1
