from __future__ import annotations

from foundation.record import Origin
from foundation.types import DiagInfo, VerifierResult
from foundation.verifier.mock import MockVerifier, ok_result
from gen.fuzzlang_dsl import (
    FUZZLANG_DSL_SCHEMA,
    FUZZLANG_DSL_VERSION,
    FuzzLangInjector,
)
from gen.realcorpus.recipes import extract_recipe
from gen.realcorpus.replay import (
    revalidate_replay_record,
    replay_source,
    round_robin_recipes,
    source_diverse_recipes,
)

from gen.realcorpus.tests.test_recipes import _record


def _error(name: str) -> VerifierResult:
    diag = DiagInfo(
        diag_id=7,
        diag_name=name,
        diag_msg="bad address operand",
        file="ignored.cpp",
        line=1,
        col=17,
        start_byte=0,
        end_byte=20,
        span_snippet="return &value;",
    )
    return VerifierResult(
        ok=False,
        diag=diag,
        raw_stderr="llvm/lib/New.cpp:1:17: error: bad address operand\n",
    )


def _recipe():
    return extract_recipe(
        _record("ex", "int f() { return x; }", "int f() { return &x; }"),
        context_tokens=2,
    )


def test_replay_source_verifies_and_emits_canonical_record():
    source = "int g() { return value; }"
    verifier = MockVerifier(
        lambda src, cmd, logical: (
            ok_result() if src == source else
            _error("err_typecheck_invalid_lvalue_addrof")
        )
    )

    outcome = replay_source(
        source,
        path="/work/external/llvm-project/llvm/lib/New.cpp",
        compile_cmd=["__CLANG__", "-fsyntax-only", "__SRC__"],
        language="c++",
        recipes=[_recipe()],
        verifier=verifier,
        project="llvm",
        max_records=2,
    )

    assert outcome.status == "accepted"
    assert outcome.candidates_verified == 1
    assert len(outcome.records) == 1
    rec = outcome.records[0]
    assert rec.corrected_src == source
    assert rec.erroneous_src == "int g() { return &value; }"
    assert rec.provenance.origin is Origin.MUTATE
    assert rec.provenance.source == "llvm:llvm/lib/New.cpp"
    assert rec.provenance.detail["strategy"] == "learned_recipe_replay"
    assert rec.provenance.detail["generation_label"] == "exact_target"
    assert rec.provenance.detail["recipe_id"] == _recipe().recipe_id
    assert rec.primary_diagnostic.file == "llvm/lib/New.cpp"


def test_replay_source_accepts_fuzzlang_injector_with_typed_provenance():
    source = "int g() { return value; }"
    injector = FuzzLangInjector.from_recipe(_recipe())
    verifier = MockVerifier(
        lambda src, cmd, logical: (
            ok_result() if src == source else
            _error("err_typecheck_invalid_lvalue_addrof")
        )
    )

    outcome = replay_source(
        source,
        path="llvm/lib/New.cpp",
        compile_cmd=["__CLANG__", "__SRC__"],
        language="c++",
        recipes=[],
        injectors=[injector],
        verifier=verifier,
        project="llvm",
    )

    assert outcome.status == "accepted"
    record = outcome.records[0]
    assert record.provenance.detail["strategy"] == "fuzzlang_dsl_replay"
    assert record.provenance.detail["injector_id"] == injector.injector_id
    assert record.provenance.detail["injector_schema"] == FUZZLANG_DSL_SCHEMA
    assert record.provenance.detail["injector_schema_version"] == FUZZLANG_DSL_VERSION
    assert record.provenance.detail["recipe_id"] == _recipe().recipe_id
    assert record.erroneous_src == "int g() { return &value; }"


def test_replay_source_keeps_verified_near_miss_with_label():
    source = "int g() { return value; }"
    verifier = MockVerifier(
        lambda src, cmd, logical: ok_result() if src == source else _error("err_other")
    )
    outcome = replay_source(
        source,
        path="llvm/lib/New.cpp",
        compile_cmd=["__CLANG__", "__SRC__"],
        language="c++",
        recipes=[_recipe()],
        verifier=verifier,
        project="llvm",
    )
    assert outcome.records[0].provenance.detail["generation_label"] == "near_miss"
    assert outcome.records[0].primary_diagnostic.diag_name == "err_other"


def test_replay_source_rejects_test_and_training_sources_without_compiling():
    verifier = MockVerifier(lambda src, cmd, logical: ok_result())
    common = dict(
        source="int g() { return value; }",
        compile_cmd=["__CLANG__", "__SRC__"],
        language="c++",
        recipes=[_recipe()],
        verifier=verifier,
        project="llvm",
    )
    test_outcome = replay_source(path="clang/test/Sema/x.cpp", **common)
    used_outcome = replay_source(
        path="llvm/lib/Used.cpp",
        excluded_sources={"llvm:llvm/lib/Used.cpp"},
        **common,
    )
    assert test_outcome.status == "test_source"
    assert used_outcome.status == "excluded_source"
    assert verifier.call_log == []


def test_replay_source_requires_clean_corrected_tu():
    verifier = MockVerifier(lambda src, cmd, logical: _error("err_existing"))
    outcome = replay_source(
        "int g() { return value; }",
        path="llvm/lib/New.cpp",
        compile_cmd=["__CLANG__", "__SRC__"],
        language="c++",
        recipes=[_recipe()],
        verifier=verifier,
        project="llvm",
    )
    assert outcome.status == "corrected_not_clean"
    assert outcome.records == ()
    assert outcome.candidates_verified == 0


def test_replay_source_deduplicates_actual_diagnostic_per_source():
    recipe = _recipe()
    source = "int g() { return first; } int h() { return second; }"
    verifier = MockVerifier(
        lambda src, cmd, logical: ok_result() if src == source else _error(recipe.diag_name)
    )
    outcome = replay_source(
        source,
        path="llvm/lib/New.cpp",
        compile_cmd=["__CLANG__", "__SRC__"],
        language="c++",
        recipes=[recipe],
        verifier=verifier,
        project="llvm",
        max_candidates_per_recipe=8,
        max_records=8,
    )
    assert len(outcome.records) == 1


def test_recipe_schedule_covers_diagnostics_before_second_recipe():
    from dataclasses import replace

    a1 = replace(_recipe(), recipe_id="a1", diag_name="err_a", support=3)
    a2 = replace(_recipe(), recipe_id="a2", diag_name="err_a", support=1)
    b1 = replace(_recipe(), recipe_id="b1", diag_name="err_b", support=2)
    scheduled = round_robin_recipes([a2, b1, a1])
    assert [recipe.recipe_id for recipe in scheduled] == ["a1", "b1", "a2"]


def test_replay_source_honors_verification_cap():
    recipe = _recipe()
    source = "int g() { return first; } int h() { return second; }"
    verifier = MockVerifier(
        lambda src, cmd, logical: ok_result() if src == source else _error(recipe.diag_name)
    )
    outcome = replay_source(
        source,
        path="llvm/lib/New.cpp",
        compile_cmd=["__CLANG__", "__SRC__"],
        language="c++",
        recipes=[recipe],
        verifier=verifier,
        project="llvm",
        max_candidates_per_recipe=8,
        max_verifications=1,
        max_records=8,
    )
    assert outcome.candidates_verified == 1
    assert len(outcome.records) == 1


def test_source_diverse_schedule_changes_diagnostic_order_not_depth():
    from dataclasses import replace

    base = _recipe()
    recipes = []
    for diag in ("err_a", "err_b", "err_c", "err_d"):
        recipes.append(replace(base, recipe_id=f"{diag}-1", diag_name=diag, support=2))
        recipes.append(replace(base, recipe_id=f"{diag}-2", diag_name=diag, support=1))
    first = source_diverse_recipes(recipes, "llvm/lib/First.cpp")
    second = source_diverse_recipes(recipes, "llvm/lib/Second.cpp")
    assert [r.diag_name for r in first[:4]] != [r.diag_name for r in second[:4]]
    assert len({r.diag_name for r in first[:4]}) == 4
    assert len({r.diag_name for r in second[:4]}) == 4


def test_revalidate_replay_record_requires_stable_pair():
    source = "int g() { return value; }"
    verifier = MockVerifier(
        lambda src, cmd, logical: (
            ok_result() if src == source else
            _error("err_typecheck_invalid_lvalue_addrof")
        )
    )
    generated = replay_source(
        source,
        path="llvm/lib/New.cpp",
        compile_cmd=["__CLANG__", "__SRC__"],
        language="c++",
        recipes=[_recipe()],
        verifier=verifier,
        project="llvm",
    ).records[0]

    result = revalidate_replay_record(generated, verifier)

    assert result.status == "accepted"
    assert result.record.primary_diagnostic.diag_name == generated.primary_diagnostic.diag_name
    assert result.record.provenance.detail["revalidated"] is True


def test_revalidate_replay_record_rejects_diagnostic_drift():
    source = "int g() { return value; }"
    first_verifier = MockVerifier(
        lambda src, cmd, logical: (
            ok_result() if src == source else
            _error("err_typecheck_invalid_lvalue_addrof")
        )
    )
    generated = replay_source(
        source,
        path="llvm/lib/New.cpp",
        compile_cmd=["__CLANG__", "__SRC__"],
        language="c++",
        recipes=[_recipe()],
        verifier=first_verifier,
        project="llvm",
    ).records[0]
    drifted = MockVerifier(
        lambda src, cmd, logical: ok_result() if src == source else _error("err_other")
    )
    result = revalidate_replay_record(generated, drifted)
    assert result.status == "diagnostic_drift"
    assert result.record is None
