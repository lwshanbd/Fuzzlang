"""Code-aware character scanning.

A mutation must only edit *code* punctuation, not characters that sit inside a
comment or a string/char literal. This module classifies each character of a
C/C++ source as code or not, so the transforms can ignore the rest.

Scope: handles ``//`` line comments, ``/* */`` block comments, ``"..."`` string
literals and ``'...'`` char literals (with backslash escapes). Raw string
literals (``R"(...)"``) are not specially handled; that is acceptable for the
mechanical first pass because the verifier filters any resulting non-errors.
"""
from __future__ import annotations

from typing import Iterator


def code_mask(src: str) -> list[bool]:
    """Return a per-character mask: ``True`` where the char is code.

    Comment bodies and string/char-literal bodies (and their delimiters) are
    marked ``False``.
    """
    mask = [True] * len(src)
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            while i < n and src[i] != "\n":
                mask[i] = False
                i += 1
            continue
        if c == "/" and nxt == "*":
            mask[i] = False
            mask[i + 1] = False
            i += 2
            while i < n and not (src[i] == "*" and i + 1 < n and src[i + 1] == "/"):
                mask[i] = False
                i += 1
            # mark the closing */
            if i < n:
                mask[i] = False
                if i + 1 < n:
                    mask[i + 1] = False
                i += 2
            continue
        if c == '"' or c == "'":
            quote = c
            mask[i] = False
            i += 1
            while i < n:
                if src[i] == "\\":  # escape: skip next char
                    mask[i] = False
                    if i + 1 < n:
                        mask[i + 1] = False
                    i += 2
                    continue
                mask[i] = False
                if src[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        i += 1
    return mask


def iter_code_chars(src: str) -> Iterator[tuple[int, str]]:
    """Yield ``(index, char)`` for every code character (skips comments/literals)."""
    mask = code_mask(src)
    for i, keep in enumerate(mask):
        if keep:
            yield i, src[i]
