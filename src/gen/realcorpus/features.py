"""Cheap syntactic feature tags shared vocabulary. Used to rank real fragments
against a target diagnostic so the injector is tried on plausibly-inducible
fragments first. Heuristic and deliberately small.
"""
from __future__ import annotations

import re

FEATURE_VOCAB = (
    "template", "call", "pointer", "member", "class", "constexpr",
    "enum", "cast", "lambda", "operator", "virtual", "reference",
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
}


def fragment_features(text: str) -> frozenset[str]:
    return frozenset(f for f, pat in _FRAG_PATTERNS.items() if pat.search(text))


def target_features(name: str, message: str) -> frozenset[str]:
    blob = f"{name} {message}".lower()
    return frozenset(f for f, hints in _TARGET_HINTS.items()
                     if any(h in blob for h in hints))
