from __future__ import annotations

import json
import sys

from foundation.diagnostics.catalog import Catalog, DiagEntry
from foundation.types import DiagInfo, VerifierResult
from gen.fuzzlang_dsl.code_witness import (
    CodeWitnessRequest,
    apply_code_witness_patch,
    build_code_witness_messages,
    parse_code_witness_patch,
)
from gen.fuzzlang_dsl.injector import FuzzLangInjector
from gen.fuzzlang_dsl.run_local_code_witness import (
    _write_checkpoint,
    load_excluded_injector_ids,
)
from gen.fuzzlang_dsl.run_build_code_witness_requests import (
    _anchor_pattern,
    _diagnostic_names_from_jsonl,
    _ordered_diagnostic_names_from_jsonl,
    _resolve_target_entries,
    _rotated_sources,
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


def test_source_rotation_selects_different_real_source_prefixes_per_batch():
    values = ("source-a", "source-b", "source-c")

    assert _rotated_sources(values, start=0) == values
    assert _rotated_sources(values, start=1) == ("source-b", "source-c", "source-a")
    assert _rotated_sources(values, start=4) == ("source-b", "source-c", "source-a")


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
