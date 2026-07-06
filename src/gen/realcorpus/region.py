"""Split a C/C++ source into candidate editable spans (function bodies).

A span runs from a function's signature start to the matching close brace of its
body. Braces inside comments/strings are ignored via the shared code mask. Pure
text — no libclang. Good enough to give the injector a bounded, meaningful
region to edit.
"""
from __future__ import annotations

from gen.mutate._scan import code_mask


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
