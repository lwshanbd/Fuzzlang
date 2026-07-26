from __future__ import annotations

import json
from dataclasses import replace

import pytest

from foundation.record import Origin, Provenance, Record, Split
from foundation.types import DiagInfo
from gen.fuzzlang_dsl import (
    FUZZLANG_DSL_SCHEMA,
    FUZZLANG_DSL_VERSION,
    FuzzLangInjector,
    ReplayLimits,
    apply_injector,
)
from gen.realcorpus.recipes import LearnedRecipe, extract_recipe


def _record(corrected: str, erroneous: str) -> Record:
    return Record(
        record_id="example-1",
        erroneous_src=erroneous,
        corrected_src=corrected,
        diagnostics=(DiagInfo(
            diag_id=17,
            diag_name="err_example",
            diag_msg="example diagnostic",
            file="llvm/lib/Example.cpp",
            line=1,
            col=1,
            start_byte=0,
            end_byte=1,
            span_snippet="x",
        ),),
        provenance=Provenance(Origin.LLM, "llvm:llvm/lib/Example.cpp"),
        split=Split.EVAL,
    )


def _binding_recipe() -> LearnedRecipe:
    recipe = extract_recipe(
        _record(
            "int f(){ return value + 0; }",
            "int f(){ return value + value; }",
        ),
        context_tokens=2,
    )
    assert recipe is not None and recipe.portable
    return recipe


def test_recipe_conversion_is_lossless_and_versioned():
    recipe = _binding_recipe()

    injector = FuzzLangInjector.from_recipe(
        recipe,
        diag_id=17,
        limits=ReplayLimits(
            max_edit_chars=128,
            max_candidates=3,
            max_verifications=12,
        ),
    )

    assert injector.schema == FUZZLANG_DSL_SCHEMA
    assert injector.schema_version == FUZZLANG_DSL_VERSION == 2
    assert injector.injector_id.startswith("fuzzlang-v2-")
    assert injector.target_diag == recipe.diag_name
    assert injector.target_diag_id == 17
    assert injector.to_recipe() == recipe


def test_delete_recipe_conversion_preserves_empty_replacement_parts():
    recipe = extract_recipe(
        _record("int f(){ return value; }", "int f(){ return value }"),
        context_tokens=1,
    )
    assert recipe is not None
    assert recipe.operation == "delete"
    assert recipe.replacement_parts == ()

    injector = FuzzLangInjector.from_recipe(recipe)

    assert injector.replacement_parts == ()
    assert injector.to_recipe() == recipe


def test_canonical_json_and_hash_are_deterministic():
    injector = FuzzLangInjector.from_recipe(_binding_recipe(), diag_id=17)
    encoded = injector.to_json()
    reparsed = FuzzLangInjector.from_json(encoded)

    assert reparsed == injector
    assert reparsed.to_json() == encoded
    assert reparsed.content_hash == injector.content_hash
    assert json.loads(encoded)["injector_id"] == injector.injector_id
    assert " " not in encoded


def test_injector_identity_excludes_support_and_exemplar_provenance():
    recipe = _binding_recipe()
    more_evidence = replace(
        recipe,
        support=9,
        exemplar_ids=("example-1", "example-2"),
    )

    first = FuzzLangInjector.from_recipe(recipe)
    second = FuzzLangInjector.from_recipe(more_evidence)

    assert first.injector_id == second.injector_id
    assert first.content_hash != second.content_hash


def test_injector_identity_excludes_per_run_replay_budgets():
    recipe = _binding_recipe()
    pilot = FuzzLangInjector.from_recipe(
        recipe,
        limits=ReplayLimits(
            max_edit_chars=256,
            max_candidates=1,
            max_verifications=8,
        ),
    )
    scale = FuzzLangInjector.from_recipe(
        recipe,
        limits=ReplayLimits(
            max_edit_chars=256,
            max_candidates=8,
            max_verifications=50,
        ),
    )

    assert pilot.injector_id == scale.injector_id
    assert pilot.content_hash != scale.content_hash


def test_old_recipe_json_without_replacement_parts_converts_and_replays():
    recipe = extract_recipe(
        _record("int f(){ return value; }", "int f(){ return &value; }"),
        context_tokens=1,
    )
    assert recipe is not None
    old_json = recipe.to_dict()
    old_json.pop("replacement_parts")

    injector = FuzzLangInjector.from_recipe_dict(old_json)
    applications = apply_injector("int g(){ return other; }", injector)

    assert injector.to_recipe().replacement_parts == (("literal", "&"),)
    assert [application.src for application in applications] == [
        "int g(){ return &other; }"
    ]
    assert applications[0].recipe_id == injector.injector_id


def test_replay_delegates_identifier_binding_to_existing_recipe_matcher():
    injector = FuzzLangInjector.from_recipe(_binding_recipe())

    matching = apply_injector(
        "int g(){ return item + 0; }",
        injector,
    )
    mismatched = apply_injector(
        "int g(){ return item + other; }",
        FuzzLangInjector.from_recipe(extract_recipe(_record(
            "int f(){ return value + value; }",
            "int f(){ return value - value; }",
        ))),
    )

    assert [application.src for application in matching] == [
        "int g(){ return item + item; }"
    ]
    assert mismatched == []


def test_v1_fresh_identifier_round_trip_and_replay():
    recipe = extract_recipe(
        _record(
            "int f(){ return value; }",
            "int f(){ int temporary = 0; return temporary + value; }",
        ),
        allow_fresh_identifiers=True,
    )
    assert recipe is not None and recipe.portable

    injector = FuzzLangInjector.from_recipe(recipe)
    restored = FuzzLangInjector.from_json(injector.to_json())
    applications = apply_injector(
        "int g(){ return item; }", restored,
    )

    assert restored.schema_version == 2
    assert restored.injector_id.startswith("fuzzlang-v2-")
    assert [application.src for application in applications] == [
        "int g(){ int fuzzlang_tmp = 0; return fuzzlang_tmp + item; }"
    ]


def test_v2_append_injector_replays_at_end_of_real_source():
    injector = FuzzLangInjector(
        target_diag="err_example",
        target_diag_id=17,
        language="c++",
        operation="append",
        old_patterns=(),
        new_text="static_assert(false, \"fuzzlang\");",
        left_context=(),
        right_context=(),
        portable=True,
        replacement_parts=(("literal", "static_assert(false, \"fuzzlang\");"),),
        schema_version=2,
    )

    applications = apply_injector("int f() { return 0; }\n", injector)

    assert injector.injector_id.startswith("fuzzlang-v2-")
    assert [application.src for application in applications] == [
        'int f() { return 0; }\nstatic_assert(false, "fuzzlang");'
    ]


def test_parser_retains_backward_compatible_v0_injectors():
    current = FuzzLangInjector.from_recipe(_binding_recipe())
    legacy = FuzzLangInjector(
        target_diag=current.target_diag,
        target_diag_id=current.target_diag_id,
        language=current.language,
        operation=current.operation,
        old_patterns=current.old_patterns,
        new_text=current.new_text,
        left_context=current.left_context,
        right_context=current.right_context,
        portable=current.portable,
        replacement_parts=current.replacement_parts,
        limits=current.limits,
        support=current.support,
        exemplar_ids=current.exemplar_ids,
        source_recipe_id=current.source_recipe_id,
        schema_version=0,
    )

    restored = FuzzLangInjector.from_json(legacy.to_json())

    assert restored == legacy
    assert restored.injector_id.startswith("fuzzlang-v0-")


def test_v0_parser_rejects_v1_fresh_identifier_semantics():
    recipe = extract_recipe(
        _record(
            "int f(){ return value; }",
            "int f(){ int temporary = 0; return temporary + value; }",
        ),
        allow_fresh_identifiers=True,
    )
    payload = FuzzLangInjector.from_recipe(recipe).to_dict()
    payload["schema_version"] = 0
    payload.pop("injector_id")

    with pytest.raises(ValueError, match="replacement part"):
        FuzzLangInjector.from_dict(payload)


def test_replay_enforces_injector_candidate_and_edit_limits():
    injector = FuzzLangInjector.from_recipe(
        extract_recipe(_record("return x;", "return &x;"), context_tokens=1),
        limits=ReplayLimits(
            max_edit_chars=1,
            max_candidates=1,
            max_verifications=4,
        ),
    )

    applications = apply_injector(
        "int f(){ return first; } int g(){ return second; }",
        injector,
        max_candidates=20,
    )

    assert len(applications) == 1
    assert applications[0].replacement == "&"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 3),
        ("schema_version", True),
        ("language", "python"),
        ("operation", "rename"),
    ],
)
def test_parser_rejects_unsupported_schema_or_semantics(field: str, value):
    payload = FuzzLangInjector.from_recipe(_binding_recipe()).to_dict()
    if field == "language":
        payload["language"] = value
    elif field == "operation":
        payload["edit"]["operation"] = value
    else:
        payload[field] = value

    with pytest.raises(ValueError):
        FuzzLangInjector.from_dict(payload)


def test_parser_rejects_tampered_injector_id():
    payload = FuzzLangInjector.from_recipe(_binding_recipe()).to_dict()
    payload["injector_id"] = "fuzzlang-v0-deadbeefdeadbeef"

    with pytest.raises(ValueError, match="injector_id"):
        FuzzLangInjector.from_dict(payload)


def test_binding_replacement_must_reference_a_match_metavariable():
    payload = FuzzLangInjector.from_recipe(_binding_recipe()).to_dict()
    payload["edit"]["replacement_parts"] = [
        {"kind": "binding", "value": "ID99"}
    ]
    payload.pop("injector_id")

    with pytest.raises(ValueError, match="ID99"):
        FuzzLangInjector.from_dict(payload)
