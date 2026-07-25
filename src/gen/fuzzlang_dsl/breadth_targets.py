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
    r"objc\w*|arc|blocks|openmp|omp|openacc|acc|cuda|hip|hlsl|opencl|sycl|"
    r"module|modules|mmap|modulemap|pch|header_unit|pragma|pp|"
    r"c23|c2y|c17|c11|c99|"
    r"coroutine|coawait|co_await|co_return|co_yield|export|three_way|spaceship|"
    r"exceptions_disabled|seh|"
    r"implementation|ivar|property|superclass|atimport|atsign|synthesize|"
    r"selector|nullability|ownership|interface|category|protocol|"
    r"ns(?:attribute|consumed|errordomain|object|constant)|"
    r"ptrauth|kernel|spirv|receiver|message_expr|message_super|super_scope|"
    r"program_scope|"
    r"address_space|addrspace|aix|darwin|nvptx|sme|zt0|"
    r"avr|arm|aarch64|riscv|wasm|webassembly|"
    r"amdgpu|bpf|hexagon|mips|ppc|sve|rvv|neon"
    r"|availability|expected_version|modifier_expected_colon|"
    r"expected_sequence_or_directive|expected_semantic_identifier|method_proto|"
    r"avail|declare_variant|declare_target|after_super|illegal_super|"
    r"function_parameter_limit|function_scope_depth"
    r")(?:_|$)",
)

# These spellings identify C++-only parser and semantic paths.  They are
# filtered only for a C campaign; the default C++ campaign intentionally keeps
# them because they are high-value coverage targets there.
_CPP_ONLY_RE = re.compile(
    r"(?:^|_)(?:"
    r"cxx|cpp|template|typename|namespace|lambda|decltype|concept|requires|"
    r"coroutine|coawait|co_await|co_return|co_yield|explicit|friend|"
    r"constructor|destructor|static_cast|dynamic_cast|const_cast|"
    r"reinterpret_cast|operator_new|operator_delete"
    r")(?:_|$)",
)

_HIGH_VALUE_TERMS = (
    "expected", "typecheck", "invalid", "undeclared", "redefinition",
    "template", "argument", "operand", "pointer", "reference", "array",
    "function", "call", "member", "initializer", "expression", "statement",
    "declaration", "lambda", "operator", "return", "switch", "case", "cast",
)


def supports_default_diagnostic_name(name: str, *, language: str) -> bool:
    """Whether a diagnostic is plausible in a default C or C++ TU campaign."""
    if language not in {"c", "c++"}:
        raise ValueError("language must be 'c' or 'c++'")
    lowered = name.lower()
    if _SPECIAL_MODE_RE.search(lowered):
        return False
    return language != "c" or not _CPP_ONLY_RE.search(lowered)


def supports_ordinary_cpp_diagnostic_name(name: str) -> bool:
    """Compatibility wrapper for the ordinary C++ campaign filter."""
    return supports_default_diagnostic_name(name, language="c++")


def supports_ordinary_c_diagnostic_name(name: str) -> bool:
    """Whether a diagnostic is plausible in the ordinary C campaign."""
    return supports_default_diagnostic_name(name, language="c")


def diagnostic_priority(entry: DiagEntry, *, language: str = "c++") -> int | None:
    """Return an ordinary-C++ injectability score, or ``None`` if ineligible."""
    if (
        not entry.is_error
        or entry.component not in _SUPPORTED_COMPONENTS
        or not entry.message.strip()
    ):
        return None
    lowered = entry.name.lower()
    if not supports_default_diagnostic_name(lowered, language=language):
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
) -> tuple[DiagEntry, ...]:
    """Choose distinct, deterministic coverage-first TableGen error targets."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("limit must be a positive integer")
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
        score = diagnostic_priority(entry, language=language)
        if score is not None:
            ranked.append((-score, entry.name, entry))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return tuple(item[2] for item in ranked[:limit])
