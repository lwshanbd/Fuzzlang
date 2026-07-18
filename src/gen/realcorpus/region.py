"""Split a C/C++ source into candidate editable spans (function bodies).

A span runs from a function's signature start to the matching close brace of its
body. Braces inside comments/strings are ignored via the shared code mask. Pure
text — no libclang. Good enough to give the injector a bounded, meaningful
region to edit.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from gen.mutate._scan import code_mask


@dataclass(frozen=True)
class Region:
    start: int
    end: int
    kind: str

    @property
    def span(self) -> tuple[int, int]:
        return self.start, self.end


def select_regions(src: str, *, max_regions: int = 8,
                   min_lines: int = 2) -> list[tuple[int, int]]:
    """Return up to `max_regions` (start, end) char spans of function bodies.

    Heuristic: find a code `{` whose nearest preceding non-space code char is
    `)` (a function/ctor body opener), then match to its `}`. The span starts at
    the line containing the signature and ends just after the close brace.
    """
    mask = code_mask(src)
    spans: list[tuple[int, int]] = []
    n = len(src)
    i = 0
    while i < n and len(spans) < max_regions:
        if mask[i] and src[i] == "{" and _preceded_by_paren(src, mask, i):
            close = _match_brace(src, mask, i)
            if close is not None:
                start = src.rfind("\n", 0, i) + 1  # start of the signature line
                end = close + 1
                if src.count("\n", start, end) >= min_lines:
                    spans.append((start, end))
                    i = end
                    continue
        i += 1
    return spans


def select_typed_regions(src: str, *, max_regions: int = 8,
                         min_lines: int = 2) -> list[Region]:
    """Return a balanced mix of function, record, and preprocessor regions.

    Diagnostics attached to declarations or preprocessing cannot be induced by
    a function-only corpus.  Round-robin selection prevents a file with many
    functions from consuming the entire per-file region budget.
    """
    functions = [Region(a, b, "function") for a, b in
                 select_regions(src, max_regions=max_regions, min_lines=min_lines)]
    mask = code_mask(src)
    visible = "".join(c if mask[i] else ("\n" if c == "\n" else " ")
                      for i, c in enumerate(src))

    records: list[Region] = []
    record_re = re.compile(
        r"\b(?:class|struct|union|enum)(?:\s+class)?\s+[A-Za-z_]\w*"
        r"[^;{}()<>]*\{")
    for match in record_re.finditer(visible):
        open_idx = visible.find("{", match.start(), match.end())
        close = _match_brace(src, mask, open_idx)
        if close is None:
            continue
        end = close + 1
        while end < len(src) and src[end].isspace() and src[end] != "\n":
            end += 1
        if end < len(src) and src[end] == ";":
            end += 1
        start = src.rfind("\n", 0, match.start()) + 1
        if src.count("\n", start, end) >= min_lines:
            records.append(Region(start, end, "record"))

    preprocessor: list[Region] = []
    pp_re = re.compile(r"(?m)^[ \t]*\#[^\n]*(?:\\\n[^\n]*)*")
    for match in pp_re.finditer(src):
        preprocessor.append(Region(match.start(), match.end(), "preprocessor"))

    buckets = [functions, records, preprocessor]
    out: list[Region] = []
    i = 0
    while len(out) < max_regions and any(i < len(bucket) for bucket in buckets):
        for bucket in buckets:
            if i < len(bucket) and len(out) < max_regions:
                out.append(bucket[i])
        i += 1
    return out


def _preceded_by_paren(src: str, mask: list[bool], brace: int) -> bool:
    j = brace - 1
    while j >= 0:
        if not mask[j] or src[j].isspace():
            j -= 1
            continue
        return src[j] == ")"
    return False


def _match_brace(src: str, mask: list[bool], open_idx: int) -> int | None:
    depth = 0
    for k in range(open_idx, len(src)):
        if not mask[k]:
            continue
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return k
    return None
