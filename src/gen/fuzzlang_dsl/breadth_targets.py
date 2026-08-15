"""Select compiler-diagnostic targets for coverage-first Injector campaigns."""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from foundation.diagnostics.catalog import DiagEntry


_SUPPORTED_COMPONENTS = frozenset({"Lex", "Parse", "Sema"})

# These diagnostics generally require a non-default language, target, driver,
# precompiled state, or preprocessor setup.  They remain in the catalog
# denominator, but are poor first-wave targets for ordinary real C++ TUs.
_SPECIAL_MODE_RE = re.compile(
    r"(?:^|_)("
    r"objc\w*|arc|blocks|openmp|omp|openacc|acc|cuda|hip|hlsl|opencl\w*|sycl|"
    r"module|modules|mmap|modulemap|pch|header_unit|pragma|pp|"
    # The current broad LLVM source pool is compiled as C++17.  Treat newer
    # C++ language modes and TS-only features as special-mode targets; they
    # belong in a future source-pool campaign with matching compile flags.
    r"coroutine|coawait|co_await|co_return|co_yield|export|three_way|spaceship|"
    r"defer_ts|"
    r"import|ms_asm|gnu_inline_asm_disabled|"
    r"exceptions_disabled|seh|"
    r"implementation|ivar|property|superclass|atimport|atsign|at_defs|at_in_class|synthesize|"
    r"selector|nullability|ownership|interface|category|protocol|"
    r"ns(?:attribute|consumed|errordomain|object|constant)|"
    r"ptrauth|kernel|spirv|receiver|message_expr|message_super|super_scope|"
    r"program_scope|"
    r"address_space|addrspace|aix|darwin|nvptx|sme|zt0|"
    r"avr|arm|aarch64|riscv|wasm|webassembly|"
    r"amdgpu|amdgcn|anyx86|x86\w*|bpf|hexagon|mips|ppc|sve|rvv|neon|interrupt"
    r"|availability|expected_version|modifier_expected_colon|"
    r"expected_sequence_or_directive|expected_semantic_identifier|method_proto|"
    r"avail|declare_variant|declare_target|after_super|illegal_super|"
    r"super_in_using|function_parameter_limit|function_scope_depth"
    r")(?:_|$)",
)

_CPP20_MODE_RE = re.compile(
    r"(?:^|_)(?:concept|requires|consteval|constinit|char8)(?:_|$)",
)
_CPP23_MODE_RE = re.compile(
    r"(?:^|_)(?:deducing_this|explicit_object|static_lambda|if_consteval)(?:_|$)",
)
_COROUTINE_MODE_RE = re.compile(
    r"(?:^|_)(?:coroutine|coawait|co_await|co_return|co_yield)(?:_|$)",
)
_SOURCE_LEVEL_EXTENSION_RE = re.compile(
    r"(?:^|_)(?:address_space|addrspace|nullability|avail(?:ability)?)(?:_|$)",
)

# The TableGen spelling is normally a useful proxy for the compiler mode an
# error needs.  These eight pinned-22.1.8 diagnostics are an intentionally
# small exception: the direct Clang regression-test scan observed each under
# ordinary ``-x c++ -std=c++2b`` with no target or feature flag.  Keeping this
# evidence-backed set explicit prevents broadening the ordinary route merely
# because a name happens to contain a target- or Objective-C-adjacent word.
# The request builder still requires a clean non-test C++23 TU and exact typed
# diagnostic replay, so this relaxes target selection rather than acceptance.
_ORDINARY_CPP23_TEST_EVIDENCED_DIAGNOSTICS = frozenset({
    "err_export_using_internal",
    "err_hidden_device_kernel",
    "err_implied_comparison_category_type_not_found",
    "err_ownership_returns_index_mismatch",
    "err_ptrauth_disabled",
    "err_wasm_funcref_not_wasm",
    "err_x86_builtin_invalid_rounding",
    "err_x86_builtin_tile_arg_duplicate",
})
# These two parser limits are also emitted by pinned Clang regression tests
# under the default C++ driver configuration (no dialect, target, or extension
# flag).  They are expensive to trigger, but are still source-level errors:
# an Injector can use compact macro or nested-declarator payloads and must pass
# the normal exact-replay gate.  Keep the exception C++-only because the test
# evidence is C++, rather than treating their names as generally ordinary-C.
_ORDINARY_CPP_TEST_EVIDENCED_DIAGNOSTICS = frozenset({
    "err_function_parameter_limit_exceeded",
    "err_function_scope_depth_exceeded",
})
# These diagnostics require a concrete frontend option, but the pinned
# Clang test suite gives that option directly.  A ``profile`` campaign must
# re-clean-gate real source with the corresponding option before synthesis;
# it is intentionally distinct from the ordinary source route.
_COMPILE_PROFILE_TEST_EVIDENCED_DIAGNOSTICS = frozenset({
    "err_defer_ts_labeled_stmt",
    "err_gnu_inline_asm_disabled",
    "err_inline_ms_asm_parsing",
    "err_seh_expected_handler",
})
_CPP_COMPILE_PROFILE_TEST_EVIDENCED_DIAGNOSTICS = frozenset({
    "err_sycl_entry_point_return_type",
    "err_sycl_external_invalid_linkage",
    "err_sycl_special_type_num_init_method",
    # This diagnostic is declared as a Warning but promoted to an error by
    # DefaultError.  The pinned Clang test uses -fsycl-is-device, so admit it
    # only through the same explicit C++ profile route.
    "warn_sycl_kernel_name_not_a_class_type",
})
_C11_MODE_RE = re.compile(r"(?:^|_)c11(?:_|$)")
_C23_MODE_RE = re.compile(r"(?:^|_)(?:c23|c2y)(?:_|$)")
_OPENMP_MODE_RE = re.compile(
    r"(?:^|_)(?:omp|openmp|declare_target|declare_variant)(?:_|$)",
)
_BLOCKS_MODE_RE = re.compile(r"(?:^|_)(?:blocks?)(?:_|$)")
_OPENACC_MODE_RE = re.compile(r"(?:^|_)(?:acc|openacc)(?:_|$)")
_OBJC_MODE_RE = re.compile(
    r"(?:^|_)(?:objc\w*|arc|implementation|ivar|property|superclass|"
    r"atimport|atsign|at_defs|at_in_class|synthesize|selector|nullability|"
    r"ownership|interface|category|protocol|ns(?:attribute|consumed|errordomain|"
    r"object|constant)|ptrauth|receiver|message_expr|message_super|super_scope|"
    r"program_scope|after_super|illegal_super|super_in_using|method_proto)(?:_|$)",
)
_MODULES_MODE_RE = re.compile(
    r"(?:^|_)(?:module|modules|modulemap|header_unit|pch|import|export)(?:_|$)",
)
_PREPROCESSOR_MODE_RE = re.compile(
    r"(?:^|_)(?:pp|pragma|directive|macro|include|"
    r"expected_sequence_or_directive|expected_semantic_identifier|"
    r"modifier_expected_colon)(?:_|$)",
)
_TARGET_MODE_RE = re.compile(
    r"(?:^|_)(?:aix|darwin|nvptx|sme|zt0|avr|arm|aarch64|riscv|wasm|"
    r"webassembly|amdgpu|amdgcn|anyx86|x86\w*|x64|bpf|hexagon|mips|ppc|"
    r"sve|rvv|neon|interrupt)(?:_|$)",
)
_NON_SOURCE_STATE_DIAGNOSTIC_RE = re.compile(r"^err_(?:drv|fe|mmap)_")

# These spellings identify C++-only parser and semantic paths.  They are
# filtered only for a C campaign; the default C++ campaign intentionally keeps
# them because they are high-value coverage targets there.
_CPP_ONLY_RE = re.compile(
    r"(?:^|_)(?:"
    r"cxx|cpp|template|typename|namespace|lambda|decltype|concept|requires|"
    r"coroutine|coawait|co_await|co_return|co_yield|explicit|friend|"
    r"constructor|destructor|static_cast|dynamic_cast|const_cast|"
    r"reinterpret_cast|operator_new|operator_delete|array_new"
    r")(?:_|$)",
)

# A number of C++ parser diagnostics predate the naming convention above and
# therefore do not contain ``cxx``/``template``/``namespace``.  They are still
# impossible to induce from a C translation unit.  Keep this deliberately
# high-precision: false positives here would discard a reachable C diagnostic,
# while false negatives merely leave a later compiler-verified rejection.
_CXX_SYNTAX_ONLY_RE = re.compile(
    r"(?:^|_)(?:"
    r"fold|parameter_pack|member_or_base|method_body|"
    r"nested_name|unqualified_id|right_angle_bracket|"
    r"placeholder_expected_auto|parentheses_around_typename|"
    r"requires_expr|assumes|deducing_this|static_lambda|"
    r"no_matching_param|nsnumber|"
    r"alias_declaration|anon_bitfield_member_init|parm_pack|"
    r"function_is_not_record|literal_operator|ctor_init|default_arg|"
    r"virt_specifier|except_spec|semi_requirement|unexpected_at"
    r")(?:_|$)",
)

# TableGen names for some C++ semantic paths use neither the explicit
# ``cxx``/``template`` spelling above nor one of the parser-only markers.
# They still cannot arise in a C11/C17 translation unit: overload resolution,
# reference binding, C++ object lifetime, and coroutine members have no C
# analogue.  Keep this separate from ``_CXX_SYNTAX_ONLY_RE`` because these are
# semantic diagnostics that otherwise looked deceptively C-compatible to the
# broad C target selector.
_CXX_SEMANTIC_ONLY_RE = re.compile(
    r"(?:^|_)(?:"
    r"ovl|deleted|this|await|type_pack|reference_bind|placement_new|"
    r"default_member_initializer|initializer_list|"
    r"pseudo_dtor|dtor|ctor|operator|mutable|defaulted|exception_spec|"
    r"virtual|override|deduced|friend|capture|consteval|"
    r"std|allocator|using|covariant|delegating|"
    r"suitable_delete|unaddressable_function|"
    r"temp_copy|ret_local_temp|ref_init|integer_sequence|"
    r"cleanup_deallocator|function_member|member_function"
    r")(?:_|$)",
)
_CONSTEXPR_DIAGNOSTIC_RE = re.compile(r"(?:^|_)constexpr(?:_|$)")

_HIGH_VALUE_TERMS = (
    "expected", "typecheck", "invalid", "undeclared", "redefinition",
    "template", "argument", "operand", "pointer", "reference", "array",
    "function", "call", "member", "initializer", "expression", "statement",
    "declaration", "lambda", "operator", "return", "switch", "case", "cast",
)


def supports_default_diagnostic_name(
    name: str, *, language: str, cpp_standard: str = "c++17",
    c_standard: str = "c17", feature_mode: str = "ordinary",
) -> bool:
    """Whether a diagnostic is plausible in a selected C/C++ TU campaign."""
    if language not in {"c", "c++"}:
        raise ValueError("language must be 'c' or 'c++'")
    if cpp_standard not in {
        "c++98", "c++11", "c++14", "c++17", "c++20", "c++23", "c++2c",
    }:
        raise ValueError(
            "cpp_standard must be one of c++98, c++11, c++14, c++17, c++20, c++23, or c++2c",
        )
    if c_standard not in {"c99", "c11", "c17", "c23"}:
        raise ValueError("c_standard must be one of c99, c11, c17, or c23")
    if feature_mode not in {
        "ordinary", "openmp", "blocks", "openacc", "objc", "modules",
        "preprocessor", "target", "profile",
    }:
        raise ValueError(
            "feature_mode must be 'ordinary', 'openmp', 'blocks', 'openacc', "
            "'objc', 'modules', 'preprocessor', 'target', or 'profile'"
        )
    lowered = name.lower()
    if (
        language == "c++"
        and cpp_standard in {"c++23", "c++2c"}
        and feature_mode == "ordinary"
        and lowered in _ORDINARY_CPP23_TEST_EVIDENCED_DIAGNOSTICS
    ):
        return True
    if (
        language == "c++"
        and feature_mode == "ordinary"
        and lowered in _ORDINARY_CPP_TEST_EVIDENCED_DIAGNOSTICS
    ):
        return True
    if (
        feature_mode == "profile"
        and (
            lowered in _COMPILE_PROFILE_TEST_EVIDENCED_DIAGNOSTICS
            or (
                language == "c++"
                and lowered in _CPP_COMPILE_PROFILE_TEST_EVIDENCED_DIAGNOSTICS
            )
        )
    ):
        return True
    if _NON_SOURCE_STATE_DIAGNOSTIC_RE.match(lowered):
        return False
    if _SPECIAL_MODE_RE.search(lowered) and not (
        feature_mode == "openmp" and _OPENMP_MODE_RE.search(lowered)
    ) and not (
        feature_mode == "blocks" and _BLOCKS_MODE_RE.search(lowered)
    ) and not (
        feature_mode == "openacc" and _OPENACC_MODE_RE.search(lowered)
    ) and not (
        feature_mode == "objc" and _OBJC_MODE_RE.search(lowered)
    ) and not (
        feature_mode == "modules" and _MODULES_MODE_RE.search(lowered)
    ) and not (
        feature_mode == "preprocessor" and _PREPROCESSOR_MODE_RE.search(lowered)
    ) and not (
        feature_mode == "target" and _TARGET_MODE_RE.search(lowered)
    ) and not (
        language == "c++"
        and cpp_standard in {"c++20", "c++23", "c++2c"}
        and _COROUTINE_MODE_RE.search(lowered)
    ) and not _SOURCE_LEVEL_EXTENSION_RE.search(lowered):
        return False
    if language == "c":
        if (
            _CPP_ONLY_RE.search(lowered)
            or _CXX_SYNTAX_ONLY_RE.search(lowered)
            or _CXX_SEMANTIC_ONLY_RE.search(lowered)
            # C23 adds ``constexpr``; retain those diagnostics only in that
            # dialect rather than treating the spelling as universally C++.
            or (
                c_standard != "c23"
                and _CONSTEXPR_DIAGNOSTIC_RE.search(lowered)
            )
        ):
            return False
        if c_standard == "c99":
            return not (_C11_MODE_RE.search(lowered) or _C23_MODE_RE.search(lowered))
        if c_standard in {"c11", "c17"}:
            return not _C23_MODE_RE.search(lowered)
        return True
    if _C11_MODE_RE.search(lowered) or _C23_MODE_RE.search(lowered):
        return False
    if cpp_standard in {"c++98", "c++11", "c++14", "c++17"}:
        return not (_CPP20_MODE_RE.search(lowered) or _CPP23_MODE_RE.search(lowered))
    if cpp_standard == "c++20":
        return not _CPP23_MODE_RE.search(lowered)
    return True


def supports_ordinary_cpp_diagnostic_name(name: str) -> bool:
    """Compatibility wrapper for the ordinary C++ campaign filter."""
    return supports_default_diagnostic_name(name, language="c++")


def supports_ordinary_c_diagnostic_name(name: str) -> bool:
    """Whether a diagnostic is plausible in the ordinary C campaign."""
    return supports_default_diagnostic_name(name, language="c")


def is_feature_specific_diagnostic_name(name: str, *, feature_mode: str) -> bool:
    """Whether a diagnostic is genuinely in a selected non-default mode."""
    lowered = name.lower()
    if feature_mode == "ordinary":
        return True
    if feature_mode == "openmp":
        return bool(_OPENMP_MODE_RE.search(lowered))
    if feature_mode == "blocks":
        return bool(_BLOCKS_MODE_RE.search(lowered))
    if feature_mode == "openacc":
        return bool(_OPENACC_MODE_RE.search(lowered))
    if feature_mode == "objc":
        return bool(_OBJC_MODE_RE.search(lowered))
    if feature_mode == "modules":
        return bool(_MODULES_MODE_RE.search(lowered))
    if feature_mode == "preprocessor":
        return bool(_PREPROCESSOR_MODE_RE.search(lowered))
    if feature_mode == "target":
        return bool(_TARGET_MODE_RE.search(lowered))
    if feature_mode == "profile":
        return lowered in (
            _COMPILE_PROFILE_TEST_EVIDENCED_DIAGNOSTICS
            | _CPP_COMPILE_PROFILE_TEST_EVIDENCED_DIAGNOSTICS
        )
    raise ValueError(f"unsupported feature_mode: {feature_mode}")


def diagnostic_priority(
    entry: DiagEntry, *, language: str = "c++", cpp_standard: str = "c++17",
    c_standard: str = "c17", feature_mode: str = "ordinary",
) -> int | None:
    """Return an ordinary-C++ injectability score, or ``None`` if ineligible."""
    if (
        not entry.is_error
        or entry.component not in _SUPPORTED_COMPONENTS
        or not entry.message.strip()
    ):
        return None
    lowered = entry.name.lower()
    if not supports_default_diagnostic_name(
        lowered, language=language, cpp_standard=cpp_standard,
        c_standard=c_standard, feature_mode=feature_mode,
    ):
        return None
    component_score = {"Parse": 300, "Sema": 200, "Lex": 100}[entry.component]
    term_score = sum(12 for term in _HIGH_VALUE_TERMS if term in lowered)
    if "expected" in lowered:
        term_score += 40
    if "template" in lowered:
        term_score += 20
    message = entry.message.lower()
    if "only allowed in" in message or "requires target feature" in message:
        term_score -= 80
    return component_score + term_score


def select_uncovered_diagnostics(
    entries: Sequence[DiagEntry] | Iterable[DiagEntry],
    *,
    covered: set[str] | frozenset[str],
    attempted: set[str] | frozenset[str],
    limit: int,
    language: str = "c++",
    cpp_standard: str = "c++17",
    c_standard: str = "c17",
    feature_mode: str = "ordinary",
    feature_specific_only: bool = False,
) -> tuple[DiagEntry, ...]:
    """Choose distinct, deterministic coverage-first TableGen error targets."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("limit must be a positive integer")
    if not isinstance(feature_specific_only, bool):
        raise ValueError("feature_specific_only must be a bool")
    ranked: list[tuple[int, str, DiagEntry]] = []
    seen: set[str] = set()
    for entry in entries:
        if (
            entry.name in seen
            or entry.name in covered
            or entry.name in attempted
        ):
            continue
        seen.add(entry.name)
        score = diagnostic_priority(
            entry, language=language, cpp_standard=cpp_standard,
            c_standard=c_standard, feature_mode=feature_mode,
        )
        if score is not None:
            if feature_specific_only and not is_feature_specific_diagnostic_name(
                entry.name, feature_mode=feature_mode,
            ):
                continue
            ranked.append((-score, entry.name, entry))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return tuple(item[2] for item in ranked[:limit])
