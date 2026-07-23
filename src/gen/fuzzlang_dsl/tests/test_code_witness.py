from __future__ import annotations

from gen.fuzzlang_dsl.code_witness import (
    CodeWitnessRequest,
    apply_code_witness_patch,
    build_code_witness_messages,
    parse_code_witness_patch,
)
from gen.fuzzlang_dsl.run_build_code_witness_requests import _anchor_pattern


def _request() -> CodeWitnessRequest:
    source = "int f() { return value; }\n"
    return CodeWitnessRequest(
        diag_name="err_expected_expression",
        diag_id=17,
        diag_message="expected expression",
        language="c++",
        tablegen_definition='def err_expected_expression : Error<"expected expression">;',
        source_id="demo:lib/f.cc",
        source_path="lib/f.cc",
        project="demo",
        compile_cmd=("__CLANG__", "-fsyntax-only", "__SRC__"),
        corrected_src=source,
        window_start=0,
        window_end=len(source),
    )


def test_code_witness_prompt_and_single_occurrence_patch_round_trip():
    request = _request()
    messages = build_code_witness_messages(request)
    patch, reason = parse_code_witness_patch(
        '{"old_text":"value", "new_text":""}', request,
    )

    assert "exactly one JSON object" in messages[0]["content"]
    assert "err_expected_expression" in messages[1]["content"]
    assert reason is None
    assert patch is not None
    assert apply_code_witness_patch(request, patch) == "int f() { return ; }\n"


def test_code_witness_rejects_ambiguous_or_non_json_patch():
    request = CodeWitnessRequest(
        diag_name="err_target",
        diag_id=None,
        diag_message="target",
        language="c++",
        tablegen_definition="def err_target : Error<\"target\">;",
        source_id="demo:lib/f.cc",
        source_path="lib/f.cc",
        project="demo",
        compile_cmd=("__CLANG__", "-fsyntax-only", "__SRC__"),
        corrected_src="int f(){ return x + x; }\n",
        window_start=0,
        window_end=len("int f(){ return x + x; }\n"),
    )

    patch, reason = parse_code_witness_patch(
        '{"old_text":"x", "new_text":""}', request,
    )

    assert patch is None
    assert reason == "old_text_not_unique_in_window"


def test_target_anchor_selection_prefers_relevant_real_code_shapes():
    assert _anchor_pattern("err_typecheck_call_too_few_args").search("f(x)")
    assert _anchor_pattern("err_typecheck_subscript_not_integer").search("a[i]")
    assert _anchor_pattern("err_typecheck_member_reference_struct_union").search("x.y")
    assert _anchor_pattern("err_typecheck_invalid_operands").search("x + y")
    assert _anchor_pattern("err_expected_expression").search("return x;")
