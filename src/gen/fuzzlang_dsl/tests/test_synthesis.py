from __future__ import annotations

import json

import pytest

from gen.fuzzlang_dsl.injector import FuzzLangInjector
from gen.fuzzlang_dsl.synthesis import (
    DiagnosticEvidence,
    SynthesisRequest,
    build_synthesis_messages,
    extract_first_json_object,
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
    assert "general AST" not in messages[0]["content"]
    user = messages[1]["content"]
    assert "err_typecheck_invalid_lvalue_addrof" in user
    assert "SemaExpr.cpp" in user
    assert "TableGen" in user
    assert "int f()" in user and "int g()" in user
    assert '"schema_version": 1' in user
    assert '"source_recipe_id": null' in user


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
