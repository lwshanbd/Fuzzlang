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
    r"objc|arc|blocks|openmp|omp|openacc|acc|cuda|hip|hlsl|opencl|sycl|"
    r"module|modules|pch|header_unit|pragma|pp|"
    r"c23|c2y|c17|c11|c99|"
    r"ptrauth|kernel|spirv|receiver|message_super|super_scope|program_scope|"
    r"avr|arm|aarch64|riscv|wasm|webassembly|"
    r"amdgpu|bpf|hexagon|mips|ppc|sve|rvv|neon"
    r")(?:_|$)",
)

_HIGH_VALUE_TERMS = (
    "expected", "typecheck", "invalid", "undeclared", "redefinition",
    "template", "argument", "operand", "pointer", "reference", "array",
    "function", "call", "member", "initializer", "expression", "statement",
    "declaration", "lambda", "operator", "return", "switch", "case", "cast",
)


def supports_ordinary_cpp_diagnostic_name(name: str) -> bool:
    """Whether a diagnostic is plausible in the campaign's C++ compile mode."""
    return not _SPECIAL_MODE_RE.search(name.lower())


def diagnostic_priority(entry: DiagEntry) -> int | None:
    """Return an ordinary-C++ injectability score, or ``None`` if ineligible."""
    if (
        not entry.is_error
        or entry.component not in _SUPPORTED_COMPONENTS
        or not entry.message.strip()
    ):
        return None
    lowered = entry.name.lower()
    if not supports_ordinary_cpp_diagnostic_name(lowered):
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
        score = diagnostic_priority(entry)
        if score is not None:
            ranked.append((-score, entry.name, entry))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return tuple(item[2] for item in ranked[:limit])
