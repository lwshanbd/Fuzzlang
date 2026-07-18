"""Cheap syntactic feature tags shared vocabulary. Used to rank real fragments
against a target diagnostic so the injector is tried on plausibly-inducible
fragments first. Heuristic and deliberately small.
"""
from __future__ import annotations

import re

FEATURE_VOCAB = (
    "template", "call", "pointer", "member", "class", "constexpr",
    "enum", "cast", "lambda", "operator", "virtual", "reference",
    "preprocessor", "attribute", "concept", "inheritance", "namespace",
    "using", "array", "atomic", "builtin", "coroutine", "exception",
    "auto", "pack", "storage", "asm",
)

# fragment-side detectors: feature -> regex on the code text.
_FRAG_PATTERNS = {
    "template": re.compile(r"\btemplate\s*<"),
    "call": re.compile(r"\w\s*\("),
    "pointer": re.compile(r"[\w>]\s*\*\s*\w|->"),
    "member": re.compile(r"->|\.\w|::"),
    "class": re.compile(r"\b(class|struct)\b"),
    "constexpr": re.compile(r"\bconstexpr\b"),
    "enum": re.compile(r"\benum\b"),
    "cast": re.compile(r"\b(static_cast|reinterpret_cast|const_cast|dynamic_cast)\b"),
    "lambda": re.compile(r"\]\s*\("),
    "operator": re.compile(r"\boperator\b"),
    "virtual": re.compile(r"\bvirtual\b"),
    "reference": re.compile(r"[\w>]\s*&\s*\w"),
    "preprocessor": re.compile(r"(?m)^\s*#\s*\w+"),
    "attribute": re.compile(r"\[\[|\b__attribute__\s*\(|\b__declspec\s*\("),
    "concept": re.compile(r"\b(concept|requires)\b"),
    "inheritance": re.compile(
        r"\b(class|struct)\s+\w+[^;{}]*:\s*(public|protected|private|virtual)?"),
    "namespace": re.compile(r"\bnamespace\b"),
    "using": re.compile(r"\b(using|typedef)\b"),
    "array": re.compile(r"\[[^\]\n]*\]"),
    "atomic": re.compile(r"\b(_Atomic|atomic(?:_|\s*<))"),
    "builtin": re.compile(r"\b__builtin_\w+"),
    "coroutine": re.compile(r"\b(co_await|co_yield|co_return)\b"),
    "exception": re.compile(r"\b(try|catch|throw|noexcept)\b"),
    "auto": re.compile(r"\b(auto|decltype)\b"),
    "pack": re.compile(r"\.\.\.|\bsizeof\s*\.\.\."),
    "storage": re.compile(r"\b(static|extern|thread_local|register)\b"),
    "asm": re.compile(r"\b(asm|__asm__)\b"),
}

# target-side keyword hints: feature -> substrings that may appear in a
# diagnostic name or message.
_TARGET_HINTS = {
    "template": ("template", "instantiat", "typename"),
    "call": ("call", "ovl", "argument", "function", "overload"),
    "pointer": ("pointer", "deref", "nullptr", "indirection"),
    "member": ("member", "->", "field", "base class"),
    "class": ("class", "struct", "abstract", "incomplete type"),
    "constexpr": ("constexpr", "constant expression", "consteval"),
    "enum": ("enum", "enumerator"),
    "cast": ("cast", "conversion", "convert"),
    "lambda": ("lambda", "capture"),
    "operator": ("operator",),
    "virtual": ("virtual", "override", "pure"),
    "reference": ("reference", "bind"),
    "preprocessor": ("pp_", "preprocessor", "macro", "#if", "#include"),
    "attribute": ("attribute", "declspec", "annotate"),
    "concept": ("concept", "constraint", "requires clause", "requires_expr"),
    "inheritance": ("base class", "derived", "inherit", "override"),
    "namespace": ("namespace",),
    "using": ("using", "typedef", "type alias"),
    "array": ("array", "subscript", "bounds"),
    "atomic": ("atomic",),
    "builtin": ("builtin",),
    "coroutine": ("coroutine", "co_await", "co_yield", "co_return"),
    "exception": ("exception", "catch", "throw", "noexcept"),
    "auto": ("auto", "deduc", "decltype", "placeholder"),
    "pack": ("parameter pack", "pack expansion", "unexpanded pack"),
    "storage": ("storage class", "thread_local", "linkage"),
    "asm": ("asm", "assembly"),
}


def fragment_features(text: str) -> frozenset[str]:
    return frozenset(f for f, pat in _FRAG_PATTERNS.items() if pat.search(text))


def target_features(name: str, message: str) -> frozenset[str]:
    blob = f"{name} {message}".lower()
    return frozenset(f for f, hints in _TARGET_HINTS.items()
                     if any(h in blob for h in hints))
