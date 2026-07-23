from __future__ import annotations

import json
import sys

from foundation.diagnostics.catalog import Catalog, DiagEntry
from foundation.types import DiagInfo, VerifierResult
from gen.fuzzlang_dsl.code_witness import (
    CodeWitnessRequest,
    apply_code_witness_patch,
    build_code_witness_messages,
    build_code_witness_retry_messages,
    parse_code_witness_patch,
)
from gen.fuzzlang_dsl.injector import FuzzLangInjector
from gen.fuzzlang_dsl.run_local_code_witness import (
    _write_checkpoint,
    load_excluded_injector_ids,
)
from gen.fuzzlang_dsl.run_build_code_witness_requests import (
    _anchor_pattern,
    _diagnostic_names_from_audits,
    _diagnostic_names_from_jsonl,
    _ordered_diagnostic_names_from_jsonl,
    _resolve_target_entries,
    _rotated_sources,
    _source_variant_orders,
)
from gen.fuzzlang_dsl import run_local_code_witness as witness_cli
from repair.agent.chat_backend import ChatResponse


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
    assert "generalize across real code" in messages[0]["content"]
    assert "err_expected_expression" in messages[1]["content"]
    assert reason is None
    assert patch is not None
    assert apply_code_witness_patch(request, patch) == "int f() { return ; }\n"


def test_code_witness_prompt_includes_optional_compiler_emission_evidence():
    request = CodeWitnessRequest(
        **{
            **_request().to_dict(),
            "emission_evidence": (
                "clang/lib/Parse/Parser.cpp:17\n"
                "Diag(Tok, diag::err_expected_expression);"
            ),
        }
    )

    messages = build_code_witness_messages(request)

    assert "compiler_emission_evidence" in messages[1]["content"]
    assert "Parser.cpp:17" in messages[1]["content"]


def test_code_witness_retry_prompt_uses_only_structured_compiler_feedback():
    request = _request()

    messages = build_code_witness_retry_messages(
        request,
        rejection_reasons=("old_text_not_unique_in_window",),
        observed_diagnostics=("err_expected_semi",),
    )

    task = json.loads(messages[1]["content"])
    assert task["prior_attempt_feedback"] == {
        "observed_primary_diagnostics": ["err_expected_semi"],
        "rejection_categories": ["old_text_not_unique_in_window"],
    }
    assert "revise the approach" in messages[0]["content"]
    assert "stderr" not in messages[1]["content"]


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


def test_target_anchor_selection_understands_parser_contexts():
    assert _anchor_pattern("err_expected_template_parameter").search(
        "template <typename T>"
    )
    assert _anchor_pattern("err_expected_end_of_enumerator").search(
        "enum Color { red, blue };"
    )
    assert _anchor_pattern("err_expected_case_before_expression").search(
        "case 1:"
    )
    assert _anchor_pattern("err_expected_init_in_condition").search(
        "if (ready)"
    )
    assert _anchor_pattern("err_expected_lbrace_after_base_specifiers").search(
        "class Child : public Base {"
    )
    assert _anchor_pattern("err_expected_fn_body").search(
        "int compute() {"
    )


def test_target_anchor_selection_uses_assignment_for_lvalue_failures():
    pattern = _anchor_pattern("err_typecheck_array_not_modifiable_lvalue")

    assert pattern.search("result = value;")
    assert pattern.search("result == value;") is None


def test_target_anchor_selection_uses_array_bounds_for_array_size_failures():
    pattern = _anchor_pattern("err_typecheck_negative_array_size")

    assert pattern.search("int values[count];")


def test_target_anchor_selection_covers_common_long_tail_cpp_contexts():
    examples = {
        "err_attribute_invalid_argument": "[[nodiscard]] int f();",
        "err_asm_invalid_output_size": 'asm("mov" : "=r"(value));',
        "err_atomic_builtin_must_be_pointer": "__atomic_load_n(ptr, 0);",
        "err_builtin_launder_invalid_arg": "__builtin_launder(pointer);",
        "err_c23_constexpr_invalid_type": "constexpr int value = 1;",
        "err_impcast_complex_scalar": "std::complex<double> value;",
        "err_constraint_not_bool": "template<class T> requires Ready<T>",
        "err_coroutine_return_type": "co_return value;",
        "err_delete_incomplete": "delete pointer;",
        "err_expected_namespace_name": "namespace detail {",
        "err_in_class_initializer_bad_type": "int member = value;",
        "err_incomplete_member_access": "class Node;",
        "err_invalid_static_assert_message": "static_assert(ready);",
        "err_lambda_in_invalid_context": "[&](int value) { return value; }",
        "err_matrix_invalid_dimension": "Matrix<int> values;",
        "err_new_incomplete_type": "new Node;",
        "err_storageclass_invalid_for_member": "static int member;",
        "err_typedef_changes_linkage": "typedef int Value;",
        "err_using_decl_nested_name_specifier_is_not_class": "using Base::value;",
        "err_vector_initializer_non_vector": "Vector<int> values;",
    }

    for diagnostic, source in examples.items():
        assert _anchor_pattern(diagnostic).search(source), diagnostic


def test_source_rotation_selects_different_real_source_prefixes_per_batch():
    values = ("source-a", "source-b", "source-c")

    assert _rotated_sources(values, start=0) == values
    assert _rotated_sources(values, start=1) == ("source-b", "source-c", "source-a")
    assert _rotated_sources(values, start=4) == ("source-b", "source-c", "source-a")


def test_source_variants_bind_each_target_to_distinct_real_source_orders():
    values = ("source-a", "source-b", "source-c", "source-d")

    assert _source_variant_orders(
        values,
        start=1,
        variants=2,
        stride=2,
    ) == (
        ("source-b", "source-c", "source-d", "source-a"),
        ("source-d", "source-a", "source-b", "source-c"),
    )


def test_coverage_first_target_resolution_uses_uncovered_unattempted_errors():
    catalog = Catalog([
        DiagEntry("err_expected_expression", "Error", "expected expression", "Parse"),
        DiagEntry("err_typecheck_invalid_operands", "Error", "invalid operands", "Sema"),
        DiagEntry("err_already_covered", "Error", "covered", "Sema"),
        DiagEntry("err_already_attempted", "Error", "attempted", "Sema"),
    ])

    selected = _resolve_target_entries(
        catalog,
        explicit_names=(),
        auto_uncovered_limit=2,
        covered={"err_already_covered"},
        attempted={"err_already_attempted"},
    )

    assert [entry.name for entry in selected] == [
        "err_expected_expression",
        "err_typecheck_invalid_operands",
    ]


def test_diagnostic_name_loader_accepts_records_and_request_rows(tmp_path):
    path = tmp_path / "mixed.jsonl"
    path.write_text(
        '{"diag_name":"err_request"}\n'
        '{"provenance":{"detail":{"target_diag":"err_record"}}}\n'
    )

    assert _diagnostic_names_from_jsonl([path]) == {
        "err_request", "err_record",
    }


def test_ordered_diagnostic_name_loader_supports_retry_queue_deduplication(tmp_path):
    first = tmp_path / "first.jsonl"
    first.write_text(
        '{"diag_name":"err_second"}\n'
        '{"diag_name":"err_first"}\n'
    )
    second = tmp_path / "second.jsonl"
    second.write_text(
        '{"diag_name":"err_second"}\n'
        '{"provenance":{"detail":{"target_diag":"err_third"}}}\n'
    )

    assert _ordered_diagnostic_names_from_jsonl([first, second]) == (
        "err_second", "err_first", "err_third",
    )


def test_diagnostic_name_loader_accepts_strict_coverage_audits(tmp_path):
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps({
        "schema": "fuzzlang.verified_injector_coverage_audit.v1",
        "verified_diagnostic_names": ["err_second", "err_first", "err_second"],
    }))

    assert _diagnostic_names_from_audits([audit]) == {
        "err_first", "err_second",
    }


def test_load_excluded_injector_identities_from_prior_campaigns(tmp_path):
    injector = FuzzLangInjector(
        target_diag="err_target",
        language="c++",
        operation="replace",
        old_patterns=("<NUM>",),
        new_text="bad",
        left_context=("return",),
        right_context=(";",),
        portable=True,
        replacement_parts=(("literal", "bad"),),
    )
    prior = tmp_path / "prior.jsonl"
    prior.write_text(json.dumps(injector.to_dict()) + "\n")

    assert load_excluded_injector_ids((prior,)) == (injector.injector_id,)


def test_code_witness_checkpoint_preserves_completed_requests(tmp_path):
    _write_checkpoint(
        tmp_path,
        attempts=[{"request_index": 0, "status": "exact_target"}],
        records=[{"record_id": "seed-1"}],
        injectors={"injector-1": {"injector_id": "injector-1"}},
    )

    assert json.loads((tmp_path / "attempts.jsonl").read_text()) == {
        "request_index": 0, "status": "exact_target",
    }
    assert json.loads((tmp_path / "records.jsonl").read_text()) == {
        "record_id": "seed-1",
    }
    assert json.loads((tmp_path / "injectors.jsonl").read_text()) == {
        "injector_id": "injector-1",
    }


def test_code_witness_cli_processes_every_request_and_writes_manifest(
    tmp_path, monkeypatch,
):
    source = "int f() { return value; }\n"
    requests = [
        CodeWitnessRequest(
            diag_name="err_typecheck_invalid_lvalue_addrof",
            diag_id=101,
            diag_message="cannot take the address of an rvalue",
            language="c++",
            tablegen_definition="def err_target : Error<\"target\">;",
            source_id=f"llvm:llvm/lib/F{index}.cpp",
            source_path=f"llvm/lib/F{index}.cpp",
            project="llvm",
            compile_cmd=("__CLANG__", "-fsyntax-only", "__SRC__"),
            corrected_src=source,
            window_start=0,
            window_end=len(source),
        )
        for index in range(2)
    ]
    request_path = tmp_path / "requests.jsonl"
    request_path.write_text("".join(
        json.dumps(request.to_dict()) + "\n" for request in requests
    ))

    class _Backend:
        def __init__(self, *args, **kwargs):
            pass

        def chat(self, *, n, **kwargs):
            return [
                ChatResponse('{"old_text":"value","new_text":"&value"}', 4)
                for _ in range(n)
            ]

    class _Verifier:
        def __init__(self, *args, **kwargs):
            pass

        def verify(self, candidate, compile_cmd, *, logical_path):
            if "&value" not in candidate:
                return VerifierResult(True, None, "")
            return VerifierResult(False, DiagInfo(
                diag_id=101,
                diag_name="err_typecheck_invalid_lvalue_addrof",
                diag_msg="target",
                file=logical_path,
                line=1,
                col=1,
                start_byte=0,
                end_byte=1,
                span_snippet="value",
            ), "")

    monkeypatch.setattr(witness_cli, "LocalGemma31BBackend", _Backend)
    monkeypatch.setattr(witness_cli, "FuzzlangClangVerifier", _Verifier)
    monkeypatch.setattr(sys, "argv", [
        "run_local_code_witness.py",
        "--requests", str(request_path),
        "--clang-bin", "/mock/clang++",
        "--clang-c-bin", "/mock/clang",
        "--diagtool-bin", "/mock/diagtool",
        "--output-dir", str(tmp_path / "out"),
        "--candidates", "1",
    ])

    assert witness_cli.main() == 0
    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text())
    assert manifest["counts"]["requests"] == 2
    assert manifest["counts"]["attempts"] == 2
    assert manifest["counts"]["records"] == 2
    # One verified seed edit is distilled at four lexical-context levels.
    # The two requests have identical edit semantics, so each level deduplicates.
    assert manifest["counts"]["portable_injectors"] == 4
    assert len((tmp_path / "out" / "injectors.jsonl").read_text().splitlines()) == 4


def test_code_witness_cli_does_not_archive_exact_but_undistillable_edits(
    tmp_path, monkeypatch,
):
    request = _request()
    request_path = tmp_path / "requests.jsonl"
    request_path.write_text(json.dumps(request.to_dict()) + "\n")

    class _Backend:
        def __init__(self, *args, **kwargs):
            pass

        def chat(self, **kwargs):
            return [ChatResponse(
                '{"old_text":"value","new_text":"bad"}', 4,
            )]

    class _Verifier:
        def __init__(self, *args, **kwargs):
            pass

        def verify(self, candidate, compile_cmd, *, logical_path):
            if "bad" not in candidate:
                return VerifierResult(True, None, "")
            return VerifierResult(False, DiagInfo(
                diag_id=17,
                diag_name="err_expected_expression",
                diag_msg="target",
                file=logical_path,
                line=1,
                col=1,
                start_byte=0,
                end_byte=1,
                span_snippet="bad",
            ), "")

    monkeypatch.setattr(witness_cli, "LocalGemma31BBackend", _Backend)
    monkeypatch.setattr(witness_cli, "FuzzlangClangVerifier", _Verifier)
    monkeypatch.setattr(
        witness_cli, "extract_contextual_injectors", lambda *args, **kwargs: (),
    )
    monkeypatch.setattr(sys, "argv", [
        "run_local_code_witness.py",
        "--requests", str(request_path),
        "--clang-bin", "/mock/clang++",
        "--clang-c-bin", "/mock/clang",
        "--diagtool-bin", "/mock/diagtool",
        "--output-dir", str(tmp_path / "out"),
        "--candidates", "1",
    ])

    assert witness_cli.main() == 0
    attempts = [
        json.loads(line)
        for line in (tmp_path / "out" / "attempts.jsonl").read_text().splitlines()
    ]
    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text())
    assert attempts[0]["status"] == "exact_target_not_distillable"
    assert manifest["counts"]["records"] == 0
    assert manifest["counts"]["portable_injectors"] == 0


def test_code_witness_cli_uses_compiler_feedback_for_second_candidate_round(
    tmp_path, monkeypatch,
):
    request = _request()
    request_path = tmp_path / "requests.jsonl"
    request_path.write_text(json.dumps(request.to_dict()) + "\n")
    calls: list[list[dict[str, str]]] = []

    class _Backend:
        def __init__(self, *args, **kwargs):
            pass

        def chat(self, *, messages, n, **kwargs):
            calls.append(messages)
            replacement = "wrong" if len(calls) == 1 else ""
            return [
                ChatResponse(
                    json.dumps({
                        "old_text": "value",
                        "new_text": replacement,
                    }),
                    4,
                )
                for _ in range(n)
            ]

    class _Verifier:
        def __init__(self, *args, **kwargs):
            pass

        def verify(self, candidate, compile_cmd, *, logical_path):
            if candidate == request.corrected_src:
                return VerifierResult(True, None, "")
            name = (
                "err_expected_expression"
                if "return ;" in candidate
                else "err_use_of_undeclared_identifier"
            )
            diag_id = 17 if name == "err_expected_expression" else 99
            return VerifierResult(False, DiagInfo(
                diag_id=diag_id,
                diag_name=name,
                diag_msg="structured only",
                file=logical_path,
                line=1,
                col=1,
                start_byte=0,
                end_byte=1,
                span_snippet="value",
            ), "")

    monkeypatch.setattr(witness_cli, "LocalGemma31BBackend", _Backend)
    monkeypatch.setattr(witness_cli, "FuzzlangClangVerifier", _Verifier)
    monkeypatch.setattr(sys, "argv", [
        "run_local_code_witness.py",
        "--requests", str(request_path),
        "--clang-bin", "/mock/clang++",
        "--clang-c-bin", "/mock/clang",
        "--diagtool-bin", "/mock/diagtool",
        "--output-dir", str(tmp_path / "out"),
        "--candidates", "2",
    ])

    assert witness_cli.main() == 0
    assert len(calls) == 2
    retry_task = json.loads(calls[1][1]["content"])
    assert retry_task["prior_attempt_feedback"][
        "observed_primary_diagnostics"
    ] == ["err_use_of_undeclared_identifier"]
    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text())
    assert manifest["counts"]["records"] == 1
    assert manifest["counts"]["feedback_round_requests"] == 1
