"""Match a rendered diagnostic message back to its diagnostic name.

This is the fallback for stock Clang, which (unlike the Fuzzlang-patched build)
does not print a numeric DiagID. Each catalog diagnostic carries a message
*template* with Clang placeholders; we convert the template to a regex and
match the actual stderr message against it.

Template constructs handled:
  %0..%9, %s0, %q0, %ordinal0, %sub{..}   -> ".*"   (a rendered argument)
  %select{a|b|c}N                          -> "(?:a|b|c)"  (options, recursive)
  %plural{1:form|:forms}N                  -> "(?:form|forms)"
  %diff{..}N,M                             -> ".*"
  %%                                       -> literal "%"
  everything else                          -> escaped literal

The DiagID path (foundation.verifier.fuzzlang) is exact and preferred; this
matcher is best-effort and intentionally returns the first template that fully
matches.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

from foundation.diagnostics.catalog import Catalog

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_PLACEHOLDER_RE = re.compile(r"%(?:ordinal|s|q)?\d+")


def _read_brace(s: str, brace_pos: int) -> tuple[str, int]:
    """`s[brace_pos]` is '{'. Return (inner_text, index_after_matching_'}')."""
    depth = 0
    for i in range(brace_pos, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return s[brace_pos + 1:i], i + 1
    raise ValueError("unmatched brace in diagnostic template")


def _skip_modifier(s: str, i: int) -> int:
    """Skip the digits/commas that follow a %select/%plural/%diff/%sub brace."""
    while i < len(s) and (s[i].isdigit() or s[i] == ","):
        i += 1
    return i


def _split_top_pipe(s: str) -> list[str]:
    """Split on '|' at brace depth 0 (top-level options)."""
    parts, depth, cur = [], 0, []
    for c in s:
        if c == "{":
            depth += 1
            cur.append(c)
        elif c == "}":
            depth -= 1
            cur.append(c)
        elif c == "|" and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(c)
    parts.append("".join(cur))
    return parts


def template_to_regex(template: str) -> str:
    """Convert a Clang diagnostic message template into a regex string."""
    out: list[str] = []
    i, n = 0, len(template)
    while i < n:
        if template.startswith("%%", i):
            out.append("%")
            i += 2
        elif template.startswith("%select{", i):
            inner, j = _read_brace(template, i + len("%select"))
            opts = _split_top_pipe(inner)
            out.append("(?:" + "|".join(template_to_regex(o) for o in opts) + ")")
            i = _skip_modifier(template, j)
        elif template.startswith("%plural{", i):
            inner, j = _read_brace(template, i + len("%plural"))
            forms = [p.split(":", 1)[-1] for p in _split_top_pipe(inner)]
            out.append("(?:" + "|".join(template_to_regex(f) for f in forms) + ")")
            i = _skip_modifier(template, j)
        elif template.startswith("%diff{", i):
            _, j = _read_brace(template, i + len("%diff"))
            out.append(".*")
            i = _skip_modifier(template, j)
        elif template.startswith("%sub{", i):
            _, j = _read_brace(template, i + len("%sub"))
            out.append(".*")
            i = _skip_modifier(template, j)
        else:
            m = _PLACEHOLDER_RE.match(template, i)
            if m:
                out.append(".*")
                i = m.end()
            else:
                out.append(re.escape(template[i]))
                i += 1
    return "".join(out)


def _normalize(message: str) -> str:
    return _ANSI_RE.sub("", message).strip()


class DiagnosticMatcher:
    """Match diagnostic messages to names using catalog message templates."""

    def __init__(self, catalog: Catalog, *, errors_only: bool = True) -> None:
        entries: Iterable = catalog.errors() if errors_only else catalog.entries
        self._patterns: list[tuple[str, re.Pattern]] = []
        for e in entries:
            pat = template_to_regex(e.message)
            if not pat or pat == ".*":      # degenerate: would match everything
                continue
            try:
                rx = re.compile(pat)
            except re.error:
                continue
            self._patterns.append((e.name, rx))

    def __len__(self) -> int:
        return len(self._patterns)

    def match(self, message: str) -> Optional[str]:
        """Return the name of the first diagnostic whose template fully matches."""
        msg = _normalize(message)
        for name, rx in self._patterns:
            if rx.fullmatch(msg):
                return name
        return None

    def candidates(self, message: str) -> list[str]:
        """Return all diagnostic names whose template fully matches."""
        msg = _normalize(message)
        return [name for name, rx in self._patterns if rx.fullmatch(msg)]
