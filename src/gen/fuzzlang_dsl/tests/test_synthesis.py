from __future__ import annotations

import json

import pytest

from gen.fuzzlang_dsl.injector import FuzzLangInjector
from gen.fuzzlang_dsl.synthesis import (
    DiagnosticEvidence,
    SynthesisRequest,
    _machine_checked_match_shapes,
    build_fragment_synthesis_messages,
    build_synthesis_messages,
    extract_first_json_object,
    validate_fragment_synthesis_responses,
    synthesize_injector,
    synthesize_injectors,
)
from repair.agent.chat_backend import ChatResponse, MockChatBackend


def _request() -> SynthesisRequest:
    return SynthesisRequest(
        diag_name="err_typecheck_invalid_lvalue_addrof",
        diag_id=4812,
        diag_message="cannot take the address of an rvalue",
        component="Sema",
        language="c++",
        evidence=DiagnosticEvidence(
            tablegen_definition=(
                "def err_typecheck_invalid_lvalue_addrof : Error<...>;"
            ),
            emission_evidence="SemaExpr.cpp emits the diagnostic for prvalues.",
        ),
        correct_snippets=(
            "int f(){ int value = 0; return value; }",
            "int g(){ int item = 1; return item; }",
        ),
    )


def _valid_payload(**overrides) -> dict:
    injector = FuzzLangInjector(
        target_diag="err_typecheck_invalid_lvalue_addrof",
        target_diag_id=4812,
        language="c++",
        operation="insert",
        old_patterns=(),
        new_text="&",
        left_context=("return",),
        right_context=("<ID0>", ";"),
        portable=True,
        replacement_parts=(("literal", "&"),),
        schema_version=1,
    )
    payload = injector.to_dict()
    payload.pop("injector_id")
    for key, value in overrides.items():
        if key == "diag_name":
            payload["target"]["diag_name"] = value
        elif key == "diag_id":
            payload["target"]["diag_id"] = value
        else:
            payload[key] = value
    return payload


def test_prompt_contains_diagnostic_evidence_real_snippets_and_v1_contract():
    messages = build_synthesis_messages(_request())

    assert [message["role"] for message in messages] == ["system", "user"]
    assert "exactly one JSON object" in messages[0]["content"]
    assert "exactly one lexer token" in messages[0]["content"]
    assert "must itself appear as an exact match token" in messages[0]["content"]
    assert "identifier spellings do not match" in messages[0]["content"]
    assert "An insert must use operation='insert', old_patterns=[]" in messages[0]["content"]
    assert '"value":"ID0"' in messages[0]["content"]
    assert "Set provenance.source_recipe_id to null" in messages[0]["content"]
    assert "FRESH0, FRESH1" in messages[0]["content"]
    assert '"replacement_parts":[{"kind":"literal","value":"&"}]' in messages[0]["content"]
    assert "general AST" not in messages[0]["content"]
    assert "No compiler-validated mutated witness has been supplied" in messages[0]["content"]
    user = messages[1]["content"]
    assert "err_typecheck_invalid_lvalue_addrof" in user
    assert "SemaExpr.cpp" in user
    assert "TableGen" in user
    assert "int f()" in user and "int g()" in user
    assert '"schema_version": 1' in user
    assert '"source_recipe_id": null' in user
    assert "machine_checked_match_shapes" in user
    assert "MUST also return match_selection" in messages[0]["content"]


def test_fragment_synthesis_accepts_bounded_v2_append_injector():
    request = _request()
    payload = FuzzLangInjector.append_fragment(
        target_diag=request.diag_name,
        diag_id=request.diag_id,
        language=request.language,
        fragment=(
            "namespace fuzzlang_generated {\n"
            "int trigger() { return &(int{0}); }\n"
            "}\n"
        ),
    ).to_dict()
    payload.pop("injector_id")

    result = validate_fragment_synthesis_responses(
        request, [ChatResponse(json.dumps(payload), 17)],
    )

    assert result.accepted_injectors[0].operation == "append"
    assert result.accepted_injectors[0].schema_version == 2


def test_fragment_synthesis_restores_omitted_request_bound_envelope_fields():
    request = _request()
    payload = FuzzLangInjector.append_fragment(
        target_diag=request.diag_name,
        diag_id=request.diag_id,
        language=request.language,
        fragment="namespace fuzzlang_generated { int trigger; }\n",
    ).to_dict()
    payload.pop("injector_id")
    payload.pop("schema")
    payload.pop("target")
    payload.pop("language")
    payload["operation"] = payload["edit"].pop("operation")

    result = validate_fragment_synthesis_responses(
        request, [ChatResponse(json.dumps(payload), 17)],
    )

    assert result.accepted_injectors[0].target_diag == request.diag_name
    assert result.accepted_injectors[0].target_diag_id == request.diag_id
    assert result.accepted_injectors[0].language == request.language
    assert result.accepted_injectors[0].operation == "append"


def test_fragment_synthesis_rejects_verbatim_regression_test_line():
    request = SynthesisRequest(
        diag_name="err_target",
        diag_id=7,
        diag_message="target message",
        component="Sema",
        language="c++",
        correct_snippets=("int a;", "int b;"),
        evidence=DiagnosticEvidence(
            emission_evidence=(
                "Regression-test trigger evidence (not a dataset source):\n"
                "int copied_test_line() { return 0; }"
            ),
        ),
    )
    payload = FuzzLangInjector.append_fragment(
        target_diag=request.diag_name,
        diag_id=request.diag_id,
        language=request.language,
        fragment=(
            "namespace fuzzlang_generated {\n"
            "int copied_test_line() { return 0; }\n"
            "}\n"
        ),
    ).to_dict()
    payload.pop("injector_id")

    result = validate_fragment_synthesis_responses(
        request, [ChatResponse(json.dumps(payload), 11)],
    )

    assert result.attempts[0].reason == "verbatim_regression_test_fragment"


def test_fragment_prompt_requires_a_new_append_only_v2_fragment():
    messages = build_fragment_synthesis_messages(_request())

    assert "schema_version=2" in messages[0]["content"]
    assert "operation='append'" in messages[0]["content"]
    assert "not copy any test line verbatim" in messages[0]["content"]


def test_machine_checked_match_shapes_normalize_real_identifiers():
    shapes = _machine_checked_match_shapes((
        "return value;", "return item;",
    ))

    assert ["return", "<ID0>", ";"] in shapes
    assert all("value" not in shape and "item" not in shape for shape in shapes)


def test_synthesis_rehydrates_match_from_model_selected_verified_shape():
    """A model may choose the edit semantics without spelling a matcher.

    The selection transport binds that edit to a lexer-confirmed real-code
    shape, preventing a hallucinated matcher from wasting an otherwise useful
    compiler-validation attempt.
    """
    request = _request()
    payload = _valid_payload()
    payload["match"] = {
        "left_context": ["not", "a", "real", "shape"],
        "old_patterns": [],
        "right_context": [],
    }
    shapes = _machine_checked_match_shapes(request.correct_snippets)
    payload["match_selection"] = {
        "shape_index": 0,
        "edit_start": len(shapes[0]),
        "edit_end": len(shapes[0]),
    }
    backend = MockChatBackend([[ChatResponse(json.dumps(payload), 11)]])

    result = synthesize_injector(request, backend)

    assert len(result.accepted_injectors) == 1
    injector = result.accepted_injectors[0]
    assert injector.left_context == tuple(shapes[0])
    assert injector.old_patterns == ()
    assert injector.right_context == ()


def test_synthesis_rejects_invalid_model_match_selection():
    payload = _valid_payload()
    payload["match_selection"] = {
        "shape_index": 99,
        "edit_start": 0,
        "edit_end": 0,
    }
    backend = MockChatBackend([[ChatResponse(json.dumps(payload), 11)]])

    result = synthesize_injector(_request(), backend)

    assert result.attempts[0].reason == "match_selection:shape_index_out_of_range"


def test_prompt_uses_requested_c_language_in_its_schema_example():
    request = SynthesisRequest(
        diag_name="err_expected_expression",
        diag_id=1,
        diag_message="expected expression",
        component="Parse",
        language="c",
        correct_snippets=("int f(void) { return 0; }", "int g(void) { return 1; }"),
    )

    system = build_synthesis_messages(request)[0]["content"]

    assert '"language":"c"' in system


def test_prompt_treats_near_miss_pair_as_revision_evidence_not_a_target_witness():
    request = SynthesisRequest(
        diag_name="err_target",
        diag_id=1,
        diag_message="target message",
        component="Sema",
        language="c++",
        evidence=DiagnosticEvidence(
            emission_evidence=(
                "Compiler replay near-miss evidence (not target-validated): "
                "a prior edit emitted another diagnostic.\n"
                "Correct local code window:\nint f(){ return 0; }\n"
                "Mutated local code window:\nint f(){ return broken; }"
            ),
        ),
        correct_snippets=("int f(){ return 0; }", "int g(){ return 1; }"),
    )

    messages = build_synthesis_messages(request)

    assert "do not copy its edit" in messages[0]["content"]
    assert "near-miss" in messages[0]["content"]


def test_prompt_uses_witness_instruction_only_when_a_witness_pair_is_present():
    request = SynthesisRequest(
        diag_name="err_target",
        diag_id=17,
        diag_message="target message",
        component="Sema",
        language="c++",
        correct_snippets=("int f() { return 0; }", "int g() { return 1; }"),
        evidence=DiagnosticEvidence(
            emission_evidence=(
                "Correct local code window:\\nint f() { return 0; }\\n"
                "Mutated local code window:\\nint f() { return ; }"
            ),
        ),
    )

    system = build_synthesis_messages(request)[0]["content"]

    assert "infer one lexical transformation from that pair" in system
    assert "No compiler-validated mutated witness has been supplied" not in system


@pytest.mark.parametrize("count", [0, 1, 6])
def test_request_requires_two_to_five_correct_real_snippets(count: int):
    with pytest.raises(ValueError, match="2 to 5"):
        SynthesisRequest(
            diag_name="err_x",
            diag_id=1,
            diag_message="m",
            component="Sema",
            language="c++",
            correct_snippets=tuple("int x;" for _ in range(count)),
        )


def test_extract_first_json_object_skips_prose_and_handles_braces_in_strings():
    text = 'analysis {not json}\n```json\n{"text":"a } brace","nested":{"x":1}}\n```'

    assert extract_first_json_object(text) == {
        "text": "a } brace",
        "nested": {"x": 1},
    }


def test_multi_candidate_synthesis_validates_and_accounts_tokens():
    accepted = _valid_payload()
    wrong_target = _valid_payload(diag_name="err_other")
    old_version = _valid_payload(schema_version=0)
    fake_recipe = _valid_payload()
    fake_recipe["provenance"]["source_recipe_id"] = "recipe-invented"
    backend = MockChatBackend([[
        ChatResponse("preface\n```json\n" + json.dumps(accepted) + "\n```", 31),
        ChatResponse("no JSON here", 7),
        ChatResponse(json.dumps(wrong_target), 19),
        ChatResponse(json.dumps(old_version), 23),
        ChatResponse(json.dumps(fake_recipe), 29),
    ]])

    result = synthesize_injectors(
        _request(),
        backend,
        n_candidates=5,
        temperature=0.2,
        max_tokens=900,
        prompt_token_counter=lambda messages: 211,
    )

    assert len(result.accepted_injectors) == 1
    assert result.accepted_injectors[0].target_diag_id == 4812
    assert [attempt.reason for attempt in result.attempts] == [
        None,
        "json_object_not_found",
        "target_name_mismatch",
        "schema_version_mismatch",
        "source_recipe_id_forbidden",
    ]
    assert result.usage.prompt_tokens == 211
    assert result.usage.output_tokens == 109
    assert result.usage.total_tokens == 320
    call = backend.call_log[0]
    assert call["n"] == 5
    assert call["max_tokens"] == 900
    assert call["response_format"]["type"] == "json_schema"


def test_single_candidate_rejects_nonportable_and_preserves_reason():
    payload = _valid_payload(portable=False)
    backend = MockChatBackend([[
        ChatResponse(json.dumps(payload), 13),
    ]])

    result = synthesize_injector(_request(), backend)

    assert result.accepted_injectors == ()
    assert result.attempts[0].status == "rejected"
    assert result.attempts[0].reason == "portable_required"
    assert result.usage.prompt_tokens is None
    assert result.usage.total_tokens is None


@pytest.mark.parametrize(
    ("override", "value", "reason"),
    [
        ("diag_id", 999, "target_id_mismatch"),
        ("language", "c", "language_mismatch"),
    ],
)
def test_synthesis_enforces_target_id_and_language(
    override: str, value, reason: str,
):
    payload = _valid_payload(**{override: value})
    backend = MockChatBackend([[ChatResponse(json.dumps(payload), 3)]])

    result = synthesize_injector(_request(), backend)

    assert result.attempts[0].reason == reason


def test_schema_validation_reason_is_recorded_without_throwing():
    payload = _valid_payload()
    payload["edit"]["operation"] = "arbitrary_python"
    backend = MockChatBackend([[ChatResponse(json.dumps(payload), 5)]])

    result = synthesize_injector(_request(), backend)

    assert result.attempts[0].reason.startswith("schema_validation:")


def test_malformed_nested_object_is_rejected_without_crashing_batch():
    payload = _valid_payload()
    payload["match"] = ["not", "an", "object"]
    backend = MockChatBackend([[ChatResponse(json.dumps(payload), 5)]])

    result = synthesize_injector(_request(), backend)

    assert result.attempts[0].status == "rejected"
    assert result.attempts[0].reason.startswith("schema_validation:")


def test_schema_valid_injector_must_apply_to_a_supplied_real_snippet():
    payload = _valid_payload()
    payload["match"]["left_context"] = ["static_assert", "(", "<ID0>", ")"]
    payload["match"]["right_context"] = []
    backend = MockChatBackend([[ChatResponse(json.dumps(payload), 9)]])

    result = synthesize_injector(_request(), backend)

    assert result.attempts[0].reason == "no_exemplar_match"


def test_synthesis_canonicalizes_raw_identifier_match_tokens_before_validation():
    payload = _valid_payload()
    payload["match"]["right_context"] = ["value", ";"]
    backend = MockChatBackend([[ChatResponse(json.dumps(payload), 9)]])

    result = synthesize_injector(_request(), backend)

    assert result.attempts[0].status == "accepted"
    assert result.accepted_injectors[0].right_context == ("<ID0>", ";")


def test_synthesis_rejects_unanchored_match_even_if_schema_accepts_it():
    payload = _valid_payload()
    payload["match"] = {
        "left_context": [],
        "old_patterns": [],
        "right_context": [],
    }
    backend = MockChatBackend([[ChatResponse(json.dumps(payload), 7)]])

    result = synthesize_injector(_request(), backend)

    assert result.attempts[0].reason == "unanchored_match"


def test_synthesis_canonicalizes_literal_exemplar_payload_whitespace():
    payload = _valid_payload()
    payload["edit"] = {
        "operation": "replace",
        "replacement_parts": [
            {"kind": "literal", "value": "static "},
            {"kind": "literal", "value": "bool "},
        ],
        "exemplar_replacement": "static bool",
    }
    payload["match"] = {
        "left_context": [],
        "old_patterns": ["return"],
        "right_context": ["<ID0>", ";"],
    }
    backend = MockChatBackend([[ChatResponse(json.dumps(payload), 11)]])

    result = synthesize_injector(_request(), backend)

    assert result.attempts[0].status == "accepted"
    assert result.accepted_injectors[0].new_text == "static bool "


def test_lexical_synthesis_restores_a_target_envelope_the_model_omitted():
    """Gemma routinely emits `"target": {}` despite the prompt repeating it.

    The append-fragment path already refills that request-determined
    boilerplate; without the same treatment every lexical candidate was
    rejected before compiler replay could judge it.
    """
    request = _request()
    payload = _valid_payload()
    payload["target"] = {}
    payload.pop("language")
    backend = MockChatBackend([[ChatResponse(json.dumps(payload), 11)]])

    result = synthesize_injector(request, backend)

    assert result.attempts[0].reason is None
    injector = result.accepted_injectors[0]
    assert injector.target_diag == request.diag_name
    assert injector.target_diag_id == request.diag_id
    assert injector.language == request.language


def test_lexical_synthesis_still_rejects_a_conflicting_model_target():
    """Restoration only fills absent fields; a wrong explicit target fails."""
    payload = _valid_payload(diag_name="err_something_else")
    backend = MockChatBackend([[ChatResponse(json.dumps(payload), 11)]])

    result = synthesize_injector(_request(), backend)

    assert result.attempts[0].reason == "target_name_mismatch"
