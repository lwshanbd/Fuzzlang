from __future__ import annotations

from foundation.diagnostics.catalog import DiagEntry
from gen.fuzzlang_dsl.breadth_targets import select_uncovered_diagnostics


def _entry(
    name: str,
    *,
    component: str = "Sema",
    message: str = "invalid expression",
    severity: str = "Error",
) -> DiagEntry:
    return DiagEntry(
        name=name,
        severity=severity,
        message=message,
        component=component,
    )


def test_select_uncovered_diagnostics_excludes_covered_attempted_and_non_errors():
    entries = [
        _entry("err_expected_expression", component="Parse"),
        _entry("err_typecheck_invalid_operands"),
        _entry("err_already_attempted"),
        _entry("warn_not_an_error", severity="Warning"),
    ]

    selected = select_uncovered_diagnostics(
        entries,
        covered={"err_typecheck_invalid_operands"},
        attempted={"err_already_attempted"},
        limit=10,
    )

    assert [entry.name for entry in selected] == ["err_expected_expression"]


def test_select_uncovered_diagnostics_rejects_special_language_and_build_modes():
    entries = [
        _entry("err_objc_invalid_receiver"),
        _entry("err_objcbridge_related_expected_related_class"),
        _entry("err_mmap_expected_header", component="Lex"),
        _entry("err_dup_implementation_class"),
        _entry("err_duplicate_ivar_use"),
        _entry("err_property_accessor_type"),
        _entry("err_unexpected_protocol_qualifier"),
        _entry("err_forward_superclass"),
        _entry("err_atimport", component="Parse"),
        _entry("err_synthesize_category_decl"),
        _entry("err_implied_coroutine_type_not_found"),
        _entry("err_illegal_message_expr_incomplete_type"),
        _entry("err_implied_comparison_category_type_not_found"),
        _entry("err_export_within_export"),
        _entry("err_three_way_vector_comparison"),
        _entry("err_exceptions_disabled"),
        _entry("err_seh_try_unsupported"),
        _entry("err_omp_expected_clause"),
        _entry("err_expected_sequence_or_directive"),
        _entry("err_modifier_expected_colon"),
        _entry("err_expected_semantic_identifier"),
        _entry("err_expected_version"),
        _entry("err_expected_semi_after_method_proto"),
        _entry("err_avail_query_expected_platform_name"),
        _entry("err_expected_begin_declare_variant"),
        _entry("err_expected_end_declare_target_or_variant"),
        _entry("err_expected_coloncolon_after_super"),
        _entry("err_illegal_super_cast"),
        _entry("err_super_in_using_declaration"),
        _entry("err_openclcxx_virtual_function"),
        _entry("err_at_defs_cxx"),
        _entry("err_at_in_class"),
        _entry("err_function_parameter_limit_exceeded"),
        _entry("err_function_scope_depth_exceeded"),
        _entry("err_cuda_bad_call"),
        _entry("err_module_not_found", component="Lex"),
        _entry("err_acc_construct_appertainment"),
        _entry("err_ptrauth_qualifier_invalid"),
        _entry("err_c23_constexpr_invalid_type"),
        _entry("err_invalid_receiver_class_message"),
        _entry("err_record_with_pointers_kernel_param"),
        _entry("err_spirv_builtin_generic_cast_invalid_arg"),
        _entry("err_sme_zt0_call_no_zt0_state"),
        _entry("err_address_space_qualified_new"),
        _entry("err_aix_attr_unsupported"),
        _entry("err_alias_not_supported_on_darwin"),
        _entry("err_alias_not_supported_on_nvptx"),
        _entry("err_drv_missing_argument", component="Driver"),
        _entry("err_empty_message", message=""),
        _entry("err_expected_semi", component="Parse"),
    ]

    selected = select_uncovered_diagnostics(
        entries, covered=set(), attempted=set(), limit=10,
    )

    assert [entry.name for entry in selected] == ["err_expected_semi"]


def test_select_uncovered_diagnostics_rejects_newer_cpp_standard_modes():
    entries = [
        _entry("err_concept_definition_not_identifier", component="Parse"),
        _entry("err_requires_clause_must_appear_after_trailing_return", component="Parse"),
        _entry("err_static_lambda_captures", component="Parse"),
        _entry("err_defer_ts_labeled_stmt", component="Parse"),
        _entry("err_import_not_allowed_here", component="Parse"),
        _entry("err_inline_ms_asm_parsing", component="Parse"),
        _entry("err_gnu_inline_asm_disabled", component="Sema"),
        _entry("err_expected_semi_after_stmt", component="Parse"),
    ]

    selected = select_uncovered_diagnostics(
        entries, covered=set(), attempted=set(), limit=10,
    )

    assert [entry.name for entry in selected] == ["err_expected_semi_after_stmt"]


def test_select_uncovered_diagnostics_prioritizes_parse_then_common_cpp_sema():
    entries = [
        _entry("err_template_argument_mismatch", message="template argument mismatch"),
        _entry("err_expected_rparen", component="Parse", message="expected ')'"),
        _entry("err_unusual_semantic_failure", message="semantic failure"),
        _entry("err_lex_failure", component="Lex", message="invalid token"),
    ]

    selected = select_uncovered_diagnostics(
        entries, covered=set(), attempted=set(), limit=3,
    )

    assert [entry.name for entry in selected] == [
        "err_expected_rparen",
        "err_template_argument_mismatch",
        "err_unusual_semantic_failure",
    ]


def test_select_uncovered_diagnostics_for_c_excludes_cpp_only_targets():
    entries = [
        _entry("err_expected_template_parameter", component="Parse"),
        _entry("err_cxx_nested_name_specifier", component="Parse"),
        _entry("err_expected_semi_after_stmt", component="Parse"),
    ]

    selected = select_uncovered_diagnostics(
        entries, covered=set(), attempted=set(), limit=10, language="c",
    )

    assert [entry.name for entry in selected] == ["err_expected_semi_after_stmt"]


def test_select_uncovered_diagnostics_is_deterministic_and_honors_limit():
    entries = [
        _entry("err_expected_z", component="Parse"),
        _entry("err_expected_a", component="Parse"),
        _entry("err_expected_m", component="Parse"),
    ]

    selected = select_uncovered_diagnostics(
        entries, covered=set(), attempted=set(), limit=2,
    )

    assert [entry.name for entry in selected] == [
        "err_expected_a",
        "err_expected_m",
    ]
