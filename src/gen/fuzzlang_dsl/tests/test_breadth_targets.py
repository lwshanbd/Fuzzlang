from __future__ import annotations

from foundation.diagnostics.catalog import DiagEntry
from gen.fuzzlang_dsl.breadth_targets import (
    select_uncovered_diagnostics,
    supports_default_diagnostic_name,
)


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
        _entry("err_expected_begin_declare_variant"),
        _entry("err_expected_end_declare_target_or_variant"),
        _entry("err_expected_coloncolon_after_super"),
        _entry("err_illegal_super_cast"),
        _entry("err_super_in_using_declaration"),
        _entry("err_openclcxx_virtual_function"),
        _entry("err_at_defs_cxx"),
        _entry("err_at_in_class"),
        _entry("err_cuda_bad_call"),
        _entry("err_module_not_found", component="Lex"),
        _entry("err_acc_construct_appertainment"),
        _entry("err_ptrauth_qualifier_invalid"),
        _entry("err_c23_constexpr_invalid_type"),
        _entry("err_invalid_receiver_class_message"),
        _entry("err_record_with_pointers_kernel_param"),
        _entry("err_spirv_builtin_generic_cast_invalid_arg"),
        _entry("err_sme_zt0_call_no_zt0_state"),
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


def test_test_evidenced_ordinary_cpp23_diagnostics_bypass_name_only_special_mode_filter():
    """Keep the route open when the pinned Clang test scan proves no flags.

    These names contain words such as ``category``, ``wasm``, or ``ptrauth``
    that are normally good special-mode signals.  Their recorded test trigger
    under the pinned compiler is nevertheless plain ``-x c++ -std=c++2b``.
    The exception only admits them to the C++23 real-source route; compiler
    replay remains the acceptance gate.
    """
    names = {
        "err_export_using_internal",
        "err_hidden_device_kernel",
        "err_implied_comparison_category_type_not_found",
        "err_ownership_returns_index_mismatch",
        "err_ptrauth_disabled",
        "err_wasm_funcref_not_wasm",
        "err_x86_builtin_invalid_rounding",
        "err_x86_builtin_tile_arg_duplicate",
    }

    assert all(
        supports_default_diagnostic_name(
            name, language="c++", cpp_standard="c++23",
        )
        for name in names
    )
    assert all(
        not supports_default_diagnostic_name(
            name, language="c++", cpp_standard="c++17",
        )
        for name in names
    )


def test_test_evidenced_ordinary_cpp_diagnostic_limits_bypass_name_filter():
    """Admit the two default-C++ parser limits observed in pinned tests."""
    names = {
        "err_function_parameter_limit_exceeded",
        "err_function_scope_depth_exceeded",
    }

    assert all(
        supports_default_diagnostic_name(
            name, language="c++", cpp_standard="c++17",
        )
        for name in names
    )
    assert all(
        not supports_default_diagnostic_name(
            name, language="c", c_standard="c17",
        )
        for name in names
    )


def test_test_evidenced_compiler_profile_diagnostics_require_profile_route():
    """Admit only explicit test-proven compiler profiles for these targets."""
    c_names = {
        "err_defer_ts_labeled_stmt",
        "err_gnu_inline_asm_disabled",
        "err_seh_expected_handler",
    }
    cpp_names = {
        "err_sycl_entry_point_return_type",
        "err_sycl_external_invalid_linkage",
        "err_sycl_special_type_num_init_method",
        "warn_sycl_kernel_name_not_a_class_type",
    }

    assert all(
        supports_default_diagnostic_name(
            name, language="c", c_standard="c17", feature_mode="profile",
        )
        for name in c_names
    )
    assert all(
        not supports_default_diagnostic_name(
            name, language="c", c_standard="c17", feature_mode="ordinary",
        )
        for name in c_names
    )
    assert all(
        supports_default_diagnostic_name(
            name, language="c++", cpp_standard="c++23", feature_mode="profile",
        )
        for name in cpp_names
    )
    assert all(
        not supports_default_diagnostic_name(
            name, language="c", c_standard="c17", feature_mode="profile",
        )
        for name in cpp_names
    )


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


def test_select_uncovered_diagnostics_allows_cpp20_targets_in_a_cpp20_campaign():
    entries = [
        _entry("err_concept_definition_not_identifier", component="Parse"),
        _entry("err_requires_clause_must_appear_after_trailing_return", component="Parse"),
        _entry("err_static_lambda_captures", component="Parse"),
        _entry("err_defer_ts_labeled_stmt", component="Parse"),
    ]

    selected = select_uncovered_diagnostics(
        entries, covered=set(), attempted=set(), limit=10, cpp_standard="c++20",
    )

    assert [entry.name for entry in selected] == [
        "err_requires_clause_must_appear_after_trailing_return",
        "err_concept_definition_not_identifier",
    ]


def test_select_uncovered_diagnostics_allows_coroutine_targets_in_cpp20_campaign():
    entries = [
        _entry("err_coroutine_return_type", component="Sema"),
    ]

    cpp17 = select_uncovered_diagnostics(
        entries, covered=set(), attempted=set(), limit=10, cpp_standard="c++17",
    )
    cpp20 = select_uncovered_diagnostics(
        entries, covered=set(), attempted=set(), limit=10, cpp_standard="c++20",
    )

    assert cpp17 == ()
    assert [entry.name for entry in cpp20] == ["err_coroutine_return_type"]


def test_defer_ts_target_requires_its_explicit_compile_profile():
    for name, language in (
        ("err_defer_ts_labeled_stmt", "c"),
        ("err_inline_ms_asm_parsing", "c++"),
    ):
        assert not supports_default_diagnostic_name(
            name, language=language, c_standard="c11", feature_mode="ordinary",
        )
        assert supports_default_diagnostic_name(
            name, language=language, c_standard="c11", feature_mode="profile",
        )


def test_select_uncovered_diagnostics_allows_source_level_address_space_and_nullability_extensions():
    entries = [
        _entry("err_address_space_qualified_new", component="Sema"),
        _entry("err_nullability_conflicting", component="Sema"),
    ]

    selected = select_uncovered_diagnostics(
        entries, covered=set(), attempted=set(), limit=10, cpp_standard="c++23",
    )

    assert {entry.name for entry in selected} == {
        "err_address_space_qualified_new", "err_nullability_conflicting",
    }


def test_select_uncovered_diagnostics_allows_source_level_availability_syntax():
    entries = [
        _entry("err_avail_query_unrecognized_platform_name", component="Parse"),
        _entry("err_availability_unknown_change", component="Parse"),
    ]

    selected = select_uncovered_diagnostics(
        entries, covered=set(), attempted=set(), limit=10, cpp_standard="c++23",
    )

    assert {entry.name for entry in selected} == {
        "err_avail_query_unrecognized_platform_name",
        "err_availability_unknown_change",
    }


def test_select_uncovered_diagnostics_allows_cpp26_targets_in_a_cpp2c_campaign():
    entries = [
        _entry("err_static_lambda_captures", component="Parse"),
        _entry("err_arith_conv_enum_float_cxx26", component="Sema"),
    ]

    selected = select_uncovered_diagnostics(
        entries, covered=set(), attempted=set(), limit=10, cpp_standard="c++2c",
    )

    assert {entry.name for entry in selected} == {
        "err_static_lambda_captures",
        "err_arith_conv_enum_float_cxx26",
    }


def test_select_uncovered_diagnostics_allows_c11_but_not_c23_in_c11_campaign():
    entries = [
        _entry("err_c11_generic_selection", component="Sema"),
        _entry("err_c23_constexpr_invalid_type", component="Sema"),
    ]

    selected = select_uncovered_diagnostics(
        entries, covered=set(), attempted=set(), limit=10,
        language="c", c_standard="c11",
    )

    assert [entry.name for entry in selected] == ["err_c11_generic_selection"]


def test_select_uncovered_diagnostics_excludes_target_and_cpp_only_c_names():
    entries = [
        _entry("err_amdgcn_coop_atomic_invalid_as"),
        _entry("err_anyx86_interrupt_called"),
        _entry("err_array_new_needs_size"),
        _entry("err_array_size_not_integral"),
    ]

    selected = select_uncovered_diagnostics(
        entries, covered=set(), attempted=set(), limit=10,
        language="c", c_standard="c11",
    )

    assert [entry.name for entry in selected] == ["err_array_size_not_integral"]


def test_select_uncovered_diagnostics_respects_c_standard_modes():
    entries = [
        _entry("err_c11_atomic_invalid", component="Sema"),
        _entry("err_c23_constexpr_invalid_type", component="Sema"),
        _entry("err_expected_semi_after_stmt", component="Parse"),
    ]

    c11 = select_uncovered_diagnostics(
        entries, covered=set(), attempted=set(), limit=10,
        language="c", c_standard="c11",
    )
    c23 = select_uncovered_diagnostics(
        entries, covered=set(), attempted=set(), limit=10,
        language="c", c_standard="c23",
    )

    assert {entry.name for entry in c11} == {
        "err_c11_atomic_invalid", "err_expected_semi_after_stmt",
    }
    assert {entry.name for entry in c23} == {
        "err_c11_atomic_invalid", "err_c23_constexpr_invalid_type",
        "err_expected_semi_after_stmt",
    }


def test_select_uncovered_diagnostics_allows_openmp_targets_only_in_openmp_mode():
    entries = [
        _entry("err_omp_expected_clause", component="Parse"),
        _entry("err_expected_semi_after_stmt", component="Parse"),
    ]

    ordinary = select_uncovered_diagnostics(
        entries, covered=set(), attempted=set(), limit=10,
    )
    openmp = select_uncovered_diagnostics(
        entries, covered=set(), attempted=set(), limit=10, feature_mode="openmp",
    )

    assert [entry.name for entry in ordinary] == ["err_expected_semi_after_stmt"]
    assert {entry.name for entry in openmp} == {
        "err_omp_expected_clause", "err_expected_semi_after_stmt",
    }


def test_select_uncovered_diagnostics_recognizes_openmp_declare_aliases():
    entries = [
        _entry("err_expected_end_declare_target_or_variant", component="Parse"),
    ]

    ordinary = select_uncovered_diagnostics(
        entries, covered=set(), attempted=set(), limit=10,
    )
    openmp = select_uncovered_diagnostics(
        entries, covered=set(), attempted=set(), limit=10, feature_mode="openmp",
    )

    assert ordinary == ()
    assert [entry.name for entry in openmp] == [
        "err_expected_end_declare_target_or_variant",
    ]


def test_select_uncovered_diagnostics_allows_blocks_targets_only_in_blocks_mode():
    entries = [
        _entry("err_blocks_unsupported_feature", component="Sema"),
        _entry("err_expected_semi_after_stmt", component="Parse"),
    ]

    ordinary = select_uncovered_diagnostics(
        entries, covered=set(), attempted=set(), limit=10,
    )
    blocks = select_uncovered_diagnostics(
        entries, covered=set(), attempted=set(), limit=10, feature_mode="blocks",
    )

    assert [entry.name for entry in ordinary] == ["err_expected_semi_after_stmt"]
    assert {entry.name for entry in blocks} == {
        "err_blocks_unsupported_feature", "err_expected_semi_after_stmt",
    }


def test_select_uncovered_diagnostics_allows_openacc_targets_only_in_openacc_mode():
    entries = [
        _entry("err_acc_construct_appertainment", component="Sema"),
        _entry("err_expected_semi_after_stmt", component="Parse"),
    ]

    ordinary = select_uncovered_diagnostics(
        entries, covered=set(), attempted=set(), limit=10,
    )
    openacc = select_uncovered_diagnostics(
        entries, covered=set(), attempted=set(), limit=10, feature_mode="openacc",
    )

    assert [entry.name for entry in ordinary] == ["err_expected_semi_after_stmt"]
    assert {entry.name for entry in openacc} == {
        "err_acc_construct_appertainment", "err_expected_semi_after_stmt",
    }


def test_feature_specific_selection_avoids_ordinary_targets_in_feature_campaigns():
    entries = [
        _entry("err_omp_expected_clause", component="Parse"),
        _entry("err_expected_semi_after_stmt", component="Parse"),
    ]

    selected = select_uncovered_diagnostics(
        entries, covered=set(), attempted=set(), limit=10, feature_mode="openmp",
        feature_specific_only=True,
    )

    assert [entry.name for entry in selected] == ["err_omp_expected_clause"]


def test_select_uncovered_diagnostics_allows_preprocessor_targets_in_preprocessor_mode():
    entries = [
        _entry("err_pp_invalid_directive", component="Lex"),
        _entry("err_expected_semi_after_stmt", component="Parse"),
    ]

    ordinary = select_uncovered_diagnostics(
        entries, covered=set(), attempted=set(), limit=10,
    )
    preprocessor = select_uncovered_diagnostics(
        entries, covered=set(), attempted=set(), limit=10,
        feature_mode="preprocessor", feature_specific_only=True,
    )

    assert [entry.name for entry in ordinary] == ["err_expected_semi_after_stmt"]
    assert [entry.name for entry in preprocessor] == ["err_pp_invalid_directive"]


def test_select_uncovered_diagnostics_allows_module_targets_in_modules_mode():
    entries = [
        _entry("err_module_not_found", component="Lex"),
        _entry("err_export_within_export", component="Sema"),
        _entry("err_expected_semi_after_stmt", component="Parse"),
    ]

    selected = select_uncovered_diagnostics(
        entries, covered=set(), attempted=set(), limit=10,
        feature_mode="modules", feature_specific_only=True,
    )

    assert {entry.name for entry in selected} == {
        "err_module_not_found", "err_export_within_export",
    }


def test_select_uncovered_diagnostics_rejects_driver_pch_and_modulemap_state_targets():
    entries = [
        _entry("err_drv_module_output_with_multiple_arch", component="Driver"),
        _entry("err_fe_no_pch_in_dir", component="Frontend"),
        _entry("err_mmap_expected_module", component="Lex"),
        _entry("err_module_not_found", component="Lex"),
    ]

    selected = select_uncovered_diagnostics(
        entries,
        covered=set(),
        attempted=set(),
        limit=10,
        feature_mode="modules",
        feature_specific_only=True,
    )

    assert [entry.name for entry in selected] == ["err_module_not_found"]
    for name in (
        "err_drv_module_output_with_multiple_arch",
        "err_fe_no_pch_in_dir",
        "err_mmap_expected_module",
    ):
        assert not supports_default_diagnostic_name(
            name, language="c++", feature_mode="modules",
        )


def test_select_uncovered_diagnostics_allows_objc_targets_in_objc_mode():
    entries = [
        _entry("err_objc_invalid_receiver", component="Sema"),
        _entry("err_expected_semi_after_stmt", component="Parse"),
    ]

    selected = select_uncovered_diagnostics(
        entries, covered=set(), attempted=set(), limit=10, language="c",
        feature_mode="objc", feature_specific_only=True,
    )

    assert [entry.name for entry in selected] == ["err_objc_invalid_receiver"]


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


def test_select_uncovered_diagnostics_for_c_excludes_cpp_syntax_without_cxx_prefix():
    """C campaigns must not spend scarce model turns on C++-only syntax.

    Several TableGen names omit an explicit ``cxx`` prefix even though the
    syntax is unambiguously C++ (for example parameter packs and nested-name
    specifiers).  The C source pool cannot witness those diagnostics.
    """
    entries = [
        _entry("err_expected_fold_operator", component="Parse"),
        _entry("err_expected_member_or_base_name", component="Parse"),
        _entry("err_expected_parameter_pack", component="Parse"),
        _entry("err_unexpected_colon_in_nested_name_spec", component="Parse"),
        _entry("err_right_angle_bracket_equal_needs_space", component="Parse"),
        _entry("err_attribute_argument_parm_pack_not_supported", component="Sema"),
        _entry("err_literal_operator_string_prefix", component="Sema"),
        _entry("err_ctor_init_missing_comma", component="Parse"),
        _entry("err_duplicate_class_virt_specifier", component="Sema"),
        _entry("err_expected_semi_after_stmt", component="Parse"),
    ]

    selected = select_uncovered_diagnostics(
        entries, covered=set(), attempted=set(), limit=10, language="c",
    )

    assert [entry.name for entry in selected] == ["err_expected_semi_after_stmt"]


def test_c_filter_rejects_cpp_semantics_with_legacy_tablegen_spellings():
    """C synthesis must not select C++ overload/lifetime diagnostics by name.

    These pinned names lack the older ``cxx``/``template`` prefixes but require
    references, overload resolution, member functions, or C++ object lifetime.
    """
    names = {
        "err_ovl_ambiguous_call",
        "err_deleted_function_use",
        "err_this_static_member_func",
        "err_default_member_initializer_cycle",
        "err_await_suspend_invalid_return_type",
        "err_type_pack_element_out_of_bounds",
        "err_reference_bind_init_list",
        "err_placement_new_non_placement_delete",
    }

    assert all(
        not supports_default_diagnostic_name(
            name, language="c", c_standard="c11",
        )
        for name in names
    )


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
