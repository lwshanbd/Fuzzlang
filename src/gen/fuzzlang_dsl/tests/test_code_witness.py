from __future__ import annotations

import json
import sys
from types import SimpleNamespace

from foundation.diagnostics.catalog import Catalog, DiagEntry
from foundation.types import DiagInfo, VerifierResult
from gen.fuzzlang_dsl.code_witness import (
    CodeAppendFragment,
    CodeWitnessRequest,
    apply_code_append_fragment,
    apply_code_witness_patch,
    build_code_append_messages,
    build_direct_injector_requests,
    build_code_witness_messages,
    build_code_witness_retry_messages,
    parse_code_witness_patch,
    parse_code_append_fragment,
)
from gen.fuzzlang_dsl.injector import FuzzLangInjector
from gen.fuzzlang_dsl.run_local_code_witness import (
    _candidate_round_counts,
    _load_resume_checkpoint,
    _known_covered_only_round_streak,
    _write_checkpoint,
    with_regression_trigger_evidence,
    is_catalog_error_diagnostic_name,
    load_excluded_injector_ids,
)
from gen.fuzzlang_dsl.run_build_code_witness_requests import (
    _attempted_diagnostic_names_from_attempts,
    _failed_diagnostic_names_from_attempts,
    _failed_target_slice,
    _anchor_pattern,
    _anchor_patterns,
    _matching_source_candidates,
    _observed_diagnostic_names_from_attempts,
    _diagnostic_names_from_audits,
    _diagnostic_names_from_jsonl,
    _ordered_diagnostic_names_from_jsonl,
    _successful_diagnostic_names_from_attempts,
    _resolve_target_entries,
    _rotated_sources,
    _source_variant_orders,
)
from gen.fuzzlang_dsl import run_local_code_witness as witness_cli
from gen.fuzzlang_dsl import run_build_direct_injector_requests as direct_cli
from gen.fuzzlang_dsl.run_build_direct_injector_requests import (
    add_regression_trigger_evidence,
    load_selected_witnesses,
)
from repair.agent.chat_backend import ChatResponse


def _request() -> CodeWitnessRequest:
    source = "int f() { return value; }\n"
    return CodeWitnessRequest(
        diag_name="err_expected_expression",
        diag_id=17,
        diag_message="expected expression",
        component="Parse",
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
    assert "must make the edited source fail compilation" in messages[0]["content"]
    assert "err_expected_expression" in messages[1]["content"]
    assert reason is None
    assert patch is not None
    assert apply_code_witness_patch(request, patch) == "int f() { return ; }\n"


def test_append_witness_prompt_and_fragment_round_trip():
    request = _request()
    messages = build_code_append_messages(request)
    fragment, reason = parse_code_append_fragment(
        '{"fragment":"int fuzzlang_bad = ;\\n"}', request,
    )

    assert "top-level declaration fragment" in messages[0]["content"]
    assert "err_expected_expression" in messages[1]["content"]
    assert reason is None
    assert fragment == CodeAppendFragment("int fuzzlang_bad = ;\n")
    assert apply_code_append_fragment(request, fragment) == (
        "int f() { return value; }\nint fuzzlang_bad = ;\n"
    )


def test_semantic_target_prompt_protects_parse_structure():
    request = CodeWitnessRequest(**{
        **_request().to_dict(),
        "diag_name": "err_typecheck_call_too_few_args",
        "diag_message": "too few arguments to function call",
    })

    messages = build_code_witness_messages(request)

    assert "preserve all delimiters, braces, statement separators" in (
        messages[0]["content"]
    )


def test_syntax_target_prompt_requires_a_local_grammar_change():
    messages = build_code_witness_messages(_request())

    assert "minimal local grammar change" in messages[0]["content"]


def test_non_undeclared_targets_forbid_identifier_removal_shortcuts():
    messages = build_code_witness_messages(_request())

    assert "Do not introduce an unknown identifier" in messages[0]["content"]


def test_direct_injector_requests_group_distinct_real_source_windows():
    first = _request()
    second = CodeWitnessRequest(**{
        **first.to_dict(),
        "source_id": "demo:lib/g.cc",
        "source_path": "lib/g.cc",
        "corrected_src": "int g() { return item; }\n",
        "window_start": 0,
        "window_end": len("int g() { return item; }\n"),
    })

    requests = build_direct_injector_requests((first, second))

    assert len(requests) == 1
    assert requests[0].diag_name == first.diag_name
    assert requests[0].component == "Parse"
    assert requests[0].correct_snippets == (first.window, second.window)
    assert requests[0].evidence.tablegen_definition == first.tablegen_definition


def test_direct_injector_requests_preserve_verified_compile_mode_as_evidence():
    first = CodeWitnessRequest(**{
        **_request().to_dict(),
        "compile_cmd": ["__CLANG__", "-std=c++20", "-fopenmp", "__SRC__"],
    })
    second = CodeWitnessRequest(**{
        **first.to_dict(),
        "source_id": "demo:lib/g.cc",
        "source_path": "lib/g.cc",
        "corrected_src": "int g() { return item; }\n",
        "window_start": 0,
        "window_end": len("int g() { return item; }\n"),
    })

    request = build_direct_injector_requests((first, second))[0]

    assert request.evidence.emission_evidence == (
        "Verified compilation mode: -std=c++20 -fopenmp"
    )


def test_direct_injector_requests_preserve_verified_modules_mode_as_evidence():
    first = CodeWitnessRequest(**{
        **_request().to_dict(),
        "compile_cmd": [
            "__CLANG__", "-std=c++20", "-fmodules", "-fcxx-modules", "__SRC__",
        ],
    })
    second = CodeWitnessRequest(**{
        **first.to_dict(),
        "source_id": "demo:lib/g.cc",
        "source_path": "lib/g.cc",
        "corrected_src": "int g() { return item; }\n",
        "window_start": 0,
        "window_end": len("int g() { return item; }\n"),
    })

    request = build_direct_injector_requests((first, second))[0]

    assert request.evidence.emission_evidence == (
        "Verified compilation mode: -std=c++20 -fmodules -fcxx-modules"
    )


def test_direct_injector_requests_preserve_verified_language_override_as_evidence():
    first = CodeWitnessRequest(**{
        **_request().to_dict(),
        "language": "c",
        "compile_cmd": ["__CLANG__", "-std=c17", "-x", "objective-c", "__SRC__"],
    })
    second = CodeWitnessRequest(**{
        **first.to_dict(),
        "source_id": "demo:lib/g.c",
        "source_path": "lib/g.c",
        "corrected_src": "int g(void) { return 0; }\n",
        "window_start": 0,
        "window_end": len("int g(void) { return 0; }\n"),
    })

    request = build_direct_injector_requests((first, second))[0]

    assert request.evidence.emission_evidence == (
        "Verified compilation mode: -std=c17 -x objective-c"
    )


def test_direct_request_loader_pools_files_and_filters_targets(tmp_path):
    first = _request()
    second = CodeWitnessRequest(**{
        **first.to_dict(),
        "diag_name": "err_other",
        "source_id": "demo:lib/g.cc",
        "source_path": "lib/g.cc",
    })
    request_file = tmp_path / "requests.jsonl"
    request_file.write_text(
        json.dumps(first.to_dict()) + "\n" + json.dumps(second.to_dict()) + "\n"
    )

    selected = load_selected_witnesses(
        [request_file], diagnostic_names={first.diag_name},
    )

    assert selected == (first,)


def test_direct_requests_keep_regression_tests_as_prompt_only_evidence(
    tmp_path, monkeypatch,
):
    first = _request()
    second = CodeWitnessRequest(**{
        **first.to_dict(),
        "source_id": "demo:lib/g.cc",
        "source_path": "lib/g.cc",
        "corrected_src": "int g() { return item; }\n",
        "window_start": 0,
        "window_end": len("int g() { return item; }\n"),
    })
    request = build_direct_injector_requests((first, second))[0]
    monkeypatch.setattr(
        direct_cli, "regression_evidence_for", lambda message, root: "test-only hint",
    )

    enriched = add_regression_trigger_evidence((request,), test_root=tmp_path)

    assert enriched[0].correct_snippets == request.correct_snippets
    assert enriched[0].evidence.emission_evidence == "test-only hint"


def test_candidate_round_counts_spread_budget_across_feedback_rounds():
    assert _candidate_round_counts(8, 4) == (2, 2, 2, 2)
    assert _candidate_round_counts(7, 3) == (3, 2, 2)
    assert _candidate_round_counts(2, 4) == (1, 1)


def test_resume_checkpoint_preserves_completed_request_rows(tmp_path):
    (tmp_path / "attempts.jsonl").write_text(
        '{"request_index":2,"status":"rejected"}\n'
    )
    (tmp_path / "records.jsonl").write_text('{"record_id":"r"}\n')
    (tmp_path / "undistillable_records.jsonl").write_text("")
    (tmp_path / "injectors.jsonl").write_text(
        '{"injector_id":"fuzzlang-v1-demo"}\n'
    )

    attempts, records, undistillable, injectors, completed = (
        _load_resume_checkpoint(tmp_path)
    )

    assert attempts == [{"request_index": 2, "status": "rejected"}]
    assert records == [{"record_id": "r"}]
    assert undistillable == []
    assert injectors == {"fuzzlang-v1-demo": {"injector_id": "fuzzlang-v1-demo"}}
    assert completed == {2}


def test_known_covered_only_round_streak_stops_repeated_unproductive_retries():
    """Do not repeatedly ask the model for the same already-covered error."""
    known_only = {"observed_diagnostic_already_covered"}

    assert _known_covered_only_round_streak(0, known_only) == 1
    assert _known_covered_only_round_streak(1, known_only) == 2
    assert _known_covered_only_round_streak(1, {"json_object_not_found"}) == 0
    assert _known_covered_only_round_streak(
        1, known_only | {"json_object_not_found"},
    ) == 0


def test_observed_admission_requires_a_pinned_catalog_error():
    catalog_error_names = frozenset({"err_expected_expression"})

    assert is_catalog_error_diagnostic_name(
        "err_expected_expression", catalog_error_names,
    )
    assert not is_catalog_error_diagnostic_name(
        "warn_unused_variable", catalog_error_names,
    )


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


def test_regression_evidence_is_prompt_only_and_preserves_the_real_source_request(
    tmp_path, monkeypatch,
):
    request = _request()
    test_root = tmp_path / "clang-test"
    test_root.mkdir()
    monkeypatch.setattr(
        witness_cli,
        "regression_evidence_for",
        lambda _message, _root: "Regression-test trigger evidence",
    )

    enriched = with_regression_trigger_evidence(request, test_root)

    assert enriched.corrected_src == request.corrected_src
    assert enriched.source_id == request.source_id
    assert enriched.emission_evidence == "Regression-test trigger evidence"


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
    assert "already-covered diagnostics are not acceptable" in (
        messages[0]["content"]
    )
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


def test_observed_diagnostic_target_ranking_uses_compiler_frequency(tmp_path):
    attempts = tmp_path / "attempts.jsonl"
    attempts.write_text("\n".join(json.dumps(item) for item in [
        {"status": "rejected", "observed_diag": "err_second"},
        {"status": "rejected", "observed_diag": "err_first"},
        {"status": "rejected", "observed_diag": "err_first"},
        {"status": "exact_target", "observed_diag": "err_ignored"},
        {"status": "rejected", "observed_diag": None},
    ]) + "\n")

    assert _observed_diagnostic_names_from_attempts(
        [attempts], min_count=1,
    ) == ("err_first", "err_second")
    assert _observed_diagnostic_names_from_attempts(
        [attempts], min_count=2,
    ) == ("err_first",)


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
        "err_count_attr_in_union": "__attribute__((counted_by(size))) int *data;",
        "err_cpu_dispatch_mismatch": '[[gnu::cpu_dispatch("sse4.2")]] void f();',
        "err_asm_invalid_output_size": 'asm("mov" : "=r"(value));',
        "err_atomic_builtin_must_be_pointer": "__atomic_load_n(ptr, 0);",
        "err_builtin_launder_invalid_arg": "__builtin_launder(pointer);",
        "err_c23_constexpr_invalid_type": "constexpr int value = 1;",
        "err_impcast_complex_scalar": "std::complex<double> value;",
        "err_constraint_not_bool": "template<class T> requires Ready<T>",
        "err_coroutine_return_type": "co_return value;",
        "err_decltype_auto_invalid": "decltype(value) result;",
        "err_decomp_decl_lambda": "auto [first, second] = pair;",
        "err_deduction_guide_bad_trailing_return_type": "Box(T) -> Box<T>;",
        "err_default_not_in_switch": "default:",
        "err_delete_incomplete": "delete pointer;",
        "err_expected_namespace_name": "namespace detail {",
        "err_final_function_overridden": "void run() final;",
        "err_first_argument_to_va_arg_not_of_type_va_list": "va_arg(args, int);",
        "err_flexible_array_not_at_end": "int data[];",
        "err_fold_expression_packs_both_sides": "(values + ...);",
        "err_in_class_initializer_bad_type": "int member = value;",
        "err_incomplete_member_access": "class Node;",
        "err_invalid_static_assert_message": "static_assert(ready);",
        "err_invalid_qualified_destructor": "object.~Widget();",
        "err_invalid_sign_spec": "unsigned int value;",
        "err_invalid_this_use": "return this;",
        "err_invalid_thread": "thread_local int value;",
        "err_lambda_in_invalid_context": "[&](int value) { return value; }",
        "err_matrix_invalid_dimension": "Matrix<int> values;",
        "err_musttail_needs_call": "[[clang::musttail]] return next();",
        "err_mutable_nonmember": "mutable int value;",
        "err_nested_name_member_ref_lookup_ambiguous": "Type::member;",
        "err_nested_redefinition": "struct Node {};",
        "err_new_abi_tag_on_redeclaration": '[[gnu::abi_tag("v1")]] void f();',
        "err_new_incomplete_type": "new Node;",
        "err_storageclass_invalid_for_member": "static int member;",
        "err_typedef_changes_linkage": "typedef int Value;",
        "err_using_decl_nested_name_specifier_is_not_class": "using Base::value;",
        "err_vector_initializer_non_vector": "Vector<int> values;",
    }

    for diagnostic, source in examples.items():
        assert _anchor_pattern(diagnostic).search(source), diagnostic


def test_target_anchor_selection_has_real_source_fallback():
    patterns = _anchor_patterns("err_new_abi_tag_on_redeclaration")

    assert patterns[0].search('[[gnu::abi_tag("v1")]] void f();')
    assert patterns[-1].search("return value;")


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


def test_source_anchor_matches_are_cached_per_pattern_and_source_order():
    sources = (
        SimpleNamespace(source_id="first", corrected_src="int f(){ return 1; }"),
        SimpleNamespace(source_id="second", corrected_src="int g(){ return 2; }"),
    )
    cache = {}
    pattern = _anchor_pattern("err_expected_expression")

    first = _matching_source_candidates(sources, pattern, cache)
    second = _matching_source_candidates(sources, pattern, cache)

    assert [source.source_id for source, _ in first] == ["first", "second"]
    assert second is first


def test_source_anchor_ignores_comment_and_literal_only_matches():
    sources = (
        SimpleNamespace(
            source_id="comment-only",
            corrected_src="// return value;\nint f(){ return 1; }",
        ),
        SimpleNamespace(
            source_id="literal-only",
            corrected_src='const char *s = "return value";\n',
        ),
    )
    pattern = _anchor_pattern("err_expected_expression")

    matched = _matching_source_candidates(sources, pattern, {})

    assert [source.source_id for source, _ in matched] == ["comment-only"]
    assert matched[0][1].start() == sources[0].corrected_src.rfind("return")


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


def test_explicit_retry_targets_drop_unreachable_cpp_modes():
    catalog = Catalog([
        DiagEntry("err_expected_expression", "Error", "expected", "Parse"),
        DiagEntry(
            "err_acc_construct_appertainment",
            "Error",
            "OpenACC-only",
            "Sema",
        ),
    ])

    selected = _resolve_target_entries(
        catalog,
        explicit_names=(
            "err_acc_construct_appertainment",
            "err_expected_expression",
        ),
        auto_uncovered_limit=None,
        covered=set(),
        attempted=set(),
    )

    assert [entry.name for entry in selected] == ["err_expected_expression"]


def test_explicit_targets_drop_catalog_errors_without_a_message_template():
    catalog = Catalog([
        DiagEntry("err_empty", "Error", "", "Sema"),
        DiagEntry("err_expected_expression", "Error", "expected", "Parse"),
    ])

    selected = _resolve_target_entries(
        catalog,
        explicit_names=("err_empty", "err_expected_expression"),
        auto_uncovered_limit=None,
        covered=set(),
        attempted=set(),
    )

    assert [entry.name for entry in selected] == ["err_expected_expression"]


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


def test_successful_attempt_loader_keeps_only_previously_exact_targets(tmp_path):
    attempts = tmp_path / "attempts.jsonl"
    attempts.write_text(
        '{"diag_name":"err_first","status":"rejected"}\n'
        '{"diag_name":"err_second","status":"exact_target"}\n'
        '{"diag_name":"err_third","status":"exact_target_not_distillable"}\n'
        '{"diag_name":"err_second","status":"exact_target"}\n'
    )

    assert _successful_diagnostic_names_from_attempts([attempts]) == (
        "err_second", "err_third",
    )


def test_failed_attempt_loader_excludes_any_target_with_an_exact_witness(tmp_path):
    attempts = tmp_path / "attempts.jsonl"
    attempts.write_text(
        '{"diag_name":"err_retry","status":"rejected"}\n'
        '{"diag_name":"err_supported","status":"rejected"}\n'
        '{"diag_name":"err_supported","status":"exact_target"}\n'
        '{"diag_name":"err_unsupported","status":"unsupported_ordinary_cpp_mode"}\n'
        '{"diag_name":"err_retry","status":"baseline_not_clean"}\n'
    )

    assert _failed_diagnostic_names_from_attempts([attempts]) == (
        "err_retry",
    )


def test_failed_target_slice_supports_disjoint_bounded_retry_batches():
    names = ("err_a", "err_b", "err_c", "err_d")

    assert _failed_target_slice(names, offset=0, limit=2) == (
        "err_a", "err_b",
    )
    assert _failed_target_slice(names, offset=2, limit=2) == (
        "err_c", "err_d",
    )


def test_attempted_target_loader_keeps_all_ordinary_attempts_in_order(tmp_path):
    attempts = tmp_path / "attempts.jsonl"
    attempts.write_text(
        '{"diag_name":"err_first","status":"rejected"}\n'
        '{"diag_name":"err_unsupported","status":"unsupported_ordinary_cpp_mode"}\n'
        '{"diag_name":"err_second","status":"exact_target"}\n'
        '{"diag_name":"err_first","status":"baseline_not_clean"}\n'
    )

    assert _attempted_diagnostic_names_from_attempts([attempts]) == (
        "err_first", "err_second",
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
        undistillable_records=[],
        injectors={"injector-1": {"injector_id": "injector-1"}},
    )

    assert json.loads((tmp_path / "attempts.jsonl").read_text()) == {
        "request_index": 0, "status": "exact_target",
    }
    assert json.loads((tmp_path / "records.jsonl").read_text()) == {
        "record_id": "seed-1",
    }
    assert (tmp_path / "undistillable_records.jsonl").read_text() == ""
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
    # Generation keeps one replay-verified, minimal Injector per witness.
    # The two requests have identical edit semantics, so that Injector deduplicates.
    assert manifest["counts"]["portable_injectors"] == 1
    injectors = [
        json.loads(line)
        for line in (tmp_path / "out" / "injectors.jsonl").read_text().splitlines()
    ]
    records = [
        json.loads(line)
        for line in (tmp_path / "out" / "records.jsonl").read_text().splitlines()
    ]
    assert len(injectors) == 1
    assert all(
        record["provenance"]["detail"]["injector_id"] == injectors[0]["injector_id"]
        for record in records
    )


def test_code_witness_cli_append_mode_extracts_a_replayable_injector(
    tmp_path, monkeypatch,
):
    request = _request()
    request_path = tmp_path / "requests.jsonl"
    request_path.write_text(json.dumps(request.to_dict()) + "\n")

    class _Backend:
        def __init__(self, *args, **kwargs):
            pass

        def chat(self, *, n, **kwargs):
            return [ChatResponse(
                '{"fragment":"int fuzzlang_bad = ;\\n"}', 4,
            ) for _ in range(n)]

    class _Verifier:
        def __init__(self, *args, **kwargs):
            pass

        def verify(self, candidate, compile_cmd, *, logical_path):
            if "int fuzzlang_bad = ;" not in candidate:
                return VerifierResult(True, None, "")
            return VerifierResult(False, DiagInfo(
                diag_id=17,
                diag_name="err_expected_expression",
                diag_msg="target",
                file=logical_path,
                line=2,
                col=20,
                start_byte=0,
                end_byte=1,
                span_snippet=";",
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
        "--witness-mode", "append",
        "--candidates", "1",
    ])

    assert witness_cli.main() == 0
    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text())
    records = [
        json.loads(line)
        for line in (tmp_path / "out" / "records.jsonl").read_text().splitlines()
    ]
    assert manifest["witness_mode"] == "append"
    assert manifest["counts"]["records"] == 1
    assert records[0]["provenance"]["detail"]["strategy"] == (
        "gemma_append_witness_injector_replay"
    )


def test_code_witness_cli_preserves_undistillable_pairs_outside_core_records(
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
    recovery_records = [
        json.loads(line)
        for line in (
            tmp_path / "out" / "undistillable_records.jsonl"
        ).read_text().splitlines()
    ]
    assert attempts[0]["status"] == "exact_target_not_distillable"
    assert manifest["counts"]["records"] == 0
    assert manifest["counts"]["undistillable_records"] == 1
    assert manifest["counts"]["portable_injectors"] == 0
    assert recovery_records[0]["corrected_src"] == request.corrected_src
    assert recovery_records[0]["erroneous_src"] != request.corrected_src


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
        "--no-admit-observed-errors",
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


def test_code_witness_cli_can_admit_an_exactly_replayed_observed_error(
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
                '{"old_text":"value","new_text":"wrong"}', 4,
            )]

    class _Verifier:
        def __init__(self, *args, **kwargs):
            pass

        def verify(self, candidate, compile_cmd, *, logical_path):
            if candidate == request.corrected_src:
                return VerifierResult(True, None, "")
            return VerifierResult(False, DiagInfo(
                diag_id=99,
                diag_name="err_undeclared_var_use",
                diag_msg="unknown identifier",
                file=logical_path,
                line=1,
                col=1,
                start_byte=0,
                end_byte=1,
                span_snippet="wrong",
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
        "--admit-observed-errors",
    ])

    assert witness_cli.main() == 0
    attempts = [
        json.loads(line)
        for line in (tmp_path / "out" / "attempts.jsonl").read_text().splitlines()
    ]
    records = [
        json.loads(line)
        for line in (tmp_path / "out" / "records.jsonl").read_text().splitlines()
    ]
    assert attempts[0]["status"] == "exact_observed_diagnostic"
    assert attempts[0]["observed_diag"] == "err_undeclared_var_use"
    assert records[0]["provenance"]["detail"]["target_diag"] == (
        "err_undeclared_var_use"
    )
    assert records[0]["provenance"]["detail"][
        "opportunistic_observed_diagnostic"
    ] is True


def test_code_witness_cli_skips_observed_types_with_an_existing_injector(
    tmp_path, monkeypatch,
):
    request = _request()
    request_path = tmp_path / "requests.jsonl"
    request_path.write_text(json.dumps(request.to_dict()) + "\n")
    excluded = tmp_path / "injectors.jsonl"
    excluded.write_text(json.dumps(FuzzLangInjector(
        target_diag="err_undeclared_var_use",
        target_diag_id=99,
        language="c++",
        operation="replace",
        old_patterns=("value",),
        new_text="wrong",
        left_context=("return",),
        right_context=(";",),
        replacement_parts=(("literal", "wrong"),),
        portable=True,
    ).to_dict()) + "\n")

    class _Backend:
        def __init__(self, *args, **kwargs):
            pass

        def chat(self, **kwargs):
            return [ChatResponse(
                '{"old_text":"value","new_text":"wrong"}', 4,
            )]

    class _Verifier:
        def __init__(self, *args, **kwargs):
            pass

        def verify(self, candidate, compile_cmd, *, logical_path):
            if candidate == request.corrected_src:
                return VerifierResult(True, None, "")
            return VerifierResult(False, DiagInfo(
                diag_id=99,
                diag_name="err_undeclared_var_use",
                diag_msg="unknown identifier",
                file=logical_path,
                line=1,
                col=1,
                start_byte=0,
                end_byte=1,
                span_snippet="wrong",
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
        "--exclude-injectors", str(excluded),
        "--candidates", "1",
    ])

    assert witness_cli.main() == 0
    attempts = [
        json.loads(line)
        for line in (tmp_path / "out" / "attempts.jsonl").read_text().splitlines()
    ]
    assert attempts[0]["reason"] == "observed_diagnostic_already_covered"
    assert (tmp_path / "out" / "records.jsonl").read_text() == ""


def test_code_witness_cli_stops_after_two_known_covered_feedback_rounds(
    tmp_path, monkeypatch,
):
    request = _request()
    request_path = tmp_path / "requests.jsonl"
    request_path.write_text(json.dumps(request.to_dict()) + "\n")
    excluded = tmp_path / "injectors.jsonl"
    excluded.write_text(json.dumps(FuzzLangInjector(
        target_diag="err_undeclared_var_use",
        target_diag_id=99,
        language="c++",
        operation="replace",
        old_patterns=("value",),
        new_text="wrong",
        left_context=("return",),
        right_context=(";",),
        replacement_parts=(("literal", "wrong"),),
        portable=True,
    ).to_dict()) + "\n")
    calls: list[int] = []

    class _Backend:
        def __init__(self, *args, **kwargs):
            pass

        def chat(self, *, n, **kwargs):
            calls.append(n)
            return [ChatResponse(
                '{"old_text":"value","new_text":"wrong"}', 4,
            ) for _ in range(n)]

    class _Verifier:
        def __init__(self, *args, **kwargs):
            pass

        def verify(self, candidate, compile_cmd, *, logical_path):
            if candidate == request.corrected_src:
                return VerifierResult(True, None, "")
            return VerifierResult(False, DiagInfo(
                diag_id=99,
                diag_name="err_undeclared_var_use",
                diag_msg="unknown identifier",
                file=logical_path,
                line=1,
                col=1,
                start_byte=0,
                end_byte=1,
                span_snippet="wrong",
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
        "--exclude-injectors", str(excluded),
        "--candidates", "4",
        "--feedback-rounds", "4",
    ])

    assert witness_cli.main() == 0
    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text())
    assert calls == [1, 1]
    assert manifest["counts"]["attempts"] == 2
    assert manifest["counts"]["known_covered_observed_short_circuits"] == 1


def test_code_witness_cli_skips_a_requested_type_with_an_existing_injector(
    tmp_path, monkeypatch,
):
    request = _request()
    request_path = tmp_path / "requests.jsonl"
    request_path.write_text(json.dumps(request.to_dict()) + "\n")
    excluded = tmp_path / "injectors.jsonl"
    excluded.write_text(json.dumps(FuzzLangInjector(
        target_diag=request.diag_name,
        target_diag_id=request.diag_id,
        language="c++",
        operation="replace",
        old_patterns=("value",),
        new_text="bad",
        left_context=("return",),
        right_context=(";",),
        replacement_parts=(("literal", "bad"),),
        portable=True,
    ).to_dict()) + "\n")

    class _Backend:
        def __init__(self, *args, **kwargs):
            pass

        def chat(self, **kwargs):
            raise AssertionError("covered target must not call Gemma")

    monkeypatch.setattr(witness_cli, "LocalGemma31BBackend", _Backend)
    monkeypatch.setattr(sys, "argv", [
        "run_local_code_witness.py",
        "--requests", str(request_path),
        "--clang-bin", "/mock/clang++",
        "--clang-c-bin", "/mock/clang",
        "--diagtool-bin", "/mock/diagtool",
        "--output-dir", str(tmp_path / "out"),
        "--exclude-injectors", str(excluded),
    ])

    assert witness_cli.main() == 0
    attempts = [
        json.loads(line)
        for line in (tmp_path / "out" / "attempts.jsonl").read_text().splitlines()
    ]
    assert attempts == [{
        "diag_name": request.diag_name,
        "request_index": 0,
        "status": "target_already_covered",
    }]


def test_code_witness_cli_skips_targets_unreachable_in_ordinary_cpp_mode(
    tmp_path, monkeypatch,
):
    request = CodeWitnessRequest(
        **{
            **_request().to_dict(),
            "diag_name": "err_acc_construct_appertainment",
        }
    )
    request_path = tmp_path / "requests.jsonl"
    request_path.write_text(json.dumps(request.to_dict()) + "\n")

    class _Backend:
        def __init__(self, *args, **kwargs):
            pass

        def chat(self, **kwargs):
            raise AssertionError("unsupported mode must not call Gemma")

    class _Verifier:
        def __init__(self, *args, **kwargs):
            pass

        def verify(self, *args, **kwargs):
            raise AssertionError("unsupported mode must skip compilation")

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
    attempts = [
        json.loads(line)
        for line in (tmp_path / "out" / "attempts.jsonl").read_text().splitlines()
    ]
    assert attempts == [{
        "diag_name": "err_acc_construct_appertainment",
        "request_index": 0,
        "status": "unsupported_ordinary_cpp_mode",
    }]


def test_code_witness_cli_does_not_apply_cpp_filter_to_c_request(
    tmp_path, monkeypatch,
):
    source = "int f(void) { return value; }\n"
    request = CodeWitnessRequest(
        diag_name="err_c23_constexpr_invalid_type",
        diag_id=101,
        diag_message="C23 target",
        component="Sema",
        language="c",
        tablegen_definition="def err_target : Error<\"target\">;",
        source_id="ffmpeg:lib/f.c",
        source_path="lib/f.c",
        project="ffmpeg",
        compile_cmd=("__CLANG__", "-std=c23", "-fsyntax-only", "__SRC__"),
        corrected_src=source,
        window_start=0,
        window_end=len(source),
    )
    request_path = tmp_path / "requests.jsonl"
    request_path.write_text(json.dumps(request.to_dict()) + "\n")

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
                diag_name="err_c23_constexpr_invalid_type",
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
    assert manifest["counts"]["records"] == 1


def test_code_witness_cli_honors_cpp20_compile_mode_for_target_filter(
    tmp_path, monkeypatch,
):
    source = "int f() { return value; }\n"
    request = CodeWitnessRequest(
        diag_name="err_invalid_consteval_call",
        diag_id=102,
        diag_message="C++20 target",
        component="Sema",
        language="c++",
        tablegen_definition="def err_target : Error<\"target\">;",
        source_id="llvm:lib/f.cpp",
        source_path="lib/f.cpp",
        project="llvm",
        compile_cmd=("__CLANG__", "-std=c++20", "-fsyntax-only", "__SRC__"),
        corrected_src=source,
        window_start=0,
        window_end=len(source),
    )
    request_path = tmp_path / "requests.jsonl"
    request_path.write_text(json.dumps(request.to_dict()) + "\n")

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
                diag_id=102,
                diag_name="err_invalid_consteval_call",
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
    assert manifest["counts"]["records"] == 1
