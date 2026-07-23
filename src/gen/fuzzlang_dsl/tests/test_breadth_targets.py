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
        _entry("err_omp_expected_clause"),
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
