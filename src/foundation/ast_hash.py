"""AST-normalized hash on a 5-line code window around a span.

For NatErr / Column A dedup. Per FINAL_PROPOSAL §Methodology line 100:
"For every Column A eval instance, the 5-line AST-normalized hash around the
span is computed. If it collides with any X-train hash, the instance is
rejected."

Two hash modes:
  - `text_normalized_hash`: cheap, whitespace-collapsed sha256 of the
    5-line window. Good enough for first-pass dedup; misses cosmetic
    rewrites (variable rename, comment shuffle).
  - `ast_normalized_hash`: parses the window with libclang, walks AST
    nodes whose extent overlaps the window, emits a normalized
    string — node kind only, no spelling/identifiers/literals — and
    hashes that. Catches cosmetic rewrites; needs libclang.

The strong guarantee for the gate is `ast_normalized_hash`. The text hash
is provided as a fast fallback / sanity check.

Public API:
    five_line_window(src, line)            -> the window text
    text_normalized_hash(src, line)        -> sha256 hex
    ast_normalized_hash(src, line, *,
                        clang_lib=None,
                        compile_args=None) -> sha256 hex
    span_hash(diag_id, file, line, col,
              snippet)                     -> the dead-end span_hash from
                                              FINAL_PROPOSAL §Method (used
                                              independently by diagnostic repair; kept
                                              here so all hashes live in
                                              one module).
"""
from __future__ import annotations

import hashlib
import os
import re
from typing import Iterable, Optional

# 5-line window: the line itself plus 2 above and 2 below.
WINDOW_RADIUS = 2


def five_line_window(src: str, line: int) -> str:
    """Return the 5-line window centered on `line` (1-indexed), clipped to
    file boundaries. Joined with \\n. Trailing newline preserved if any."""
    if line < 1:
        raise ValueError(f"line must be >= 1, got {line}")
    lines = src.splitlines()
    n = len(lines)
    lo = max(0, line - 1 - WINDOW_RADIUS)
    hi = min(n, line - 1 + WINDOW_RADIUS + 1)
    return "\n".join(lines[lo:hi])


def _normalize_text(s: str) -> str:
    """Whitespace-only normalization: collapse runs of whitespace to a
    single space per line, but PRESERVE line content (including comments)
    and PRESERVE blank lines. Otherwise two all-comment 5-line windows
    from different files collapse to identical empty strings → false
    collision.

    The job of dedup is to catch "same code in different splits", not
    "same shape with different content". Comments ARE content that
    differs across LLVM source files.
    """
    return "\n".join(" ".join(ln.split()) for ln in s.splitlines())


def text_normalized_hash(src: str, line: int) -> str:
    """sha256 over whitespace-normalized 5-line window around `line`."""
    win = five_line_window(src, line)
    norm = _normalize_text(win)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def ast_normalized_hash(
    src: str, line: int, *,
    clang_lib: Optional[str] = None,
    compile_args: Optional[Iterable[str]] = None,
) -> str:
    """sha256 over AST-shape signature of nodes overlapping the 5-line
    window. AST shape = depth-first sequence of node-kind names; no
    spelling, no displaynames, no source-extent values, no literals.

    Falls back to `text_normalized_hash` if libclang isn't available or
    the source can't be parsed.

    `clang_lib` overrides the libclang shared-library path. If None,
    we use the pine-default LLVM 17 path. `compile_args` is forwarded
    to libclang's parse() (e.g. ['-x', 'c++', '-std=c++20', '-Iinc']).
    """
    try:
        import clang.cindex as ci
    except ImportError:
        return text_normalized_hash(src, line)

    if clang_lib is None:
        clang_lib = os.environ.get(
            "FUZZLANG_LIBCLANG_PATH",
            "/hrtc/apps/devtools/spack/PINE/linux-rocky9-zen4/"
            "gcc-11.4.1/llvm-17.0.4-zwkzgzmep5nkmdjypj52qebr7dvzkc5o/"
            "lib/libclang.so",
        )
    try:
        if not ci.Config.library_file:
            ci.Config.set_library_file(clang_lib)
    except ci.LibclangError:
        return text_normalized_hash(src, line)

    args = list(compile_args or ["-x", "c++", "-std=c++20"])
    # Parse via in-memory unsaved file; no disk I/O required.
    try:
        idx = ci.Index.create()
        tu = idx.parse(
            "tmp.cpp", args=args,
            unsaved_files=[("tmp.cpp", src)],
            options=ci.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD,
        )
    except Exception:
        return text_normalized_hash(src, line)

    win_lo = max(1, line - WINDOW_RADIUS)
    win_hi = line + WINDOW_RADIUS

    sig: list[str] = []

    def _walk(node, depth: int) -> None:
        ext = node.extent
        # Skip nodes from other files / no location.
        if not (ext.start.file and ext.end.file):
            for c in node.get_children():
                _walk(c, depth + 1)
            return
        # Overlap test against [win_lo, win_hi].
        if ext.end.line < win_lo or ext.start.line > win_hi:
            return
        # Kind + spelling. Include spelling so identical AST shapes from
        # different files (boilerplate function signatures etc.) don't
        # produce false collisions; differs from identifier rename, which
        # is acceptable here — a Fuzzlang-Transformer mutation is more
        # invasive than a rename.
        spelling = node.spelling or ""
        sig.append(f"{depth}:{node.kind.name}:{spelling}")
        for c in node.get_children():
            _walk(c, depth + 1)

    _walk(tu.cursor, 0)
    if not sig:
        # AST didn't yield anything in window — degrade to text hash.
        return text_normalized_hash(src, line)
    s = "|".join(sig)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def span_hash(
    diag_id: int, file: str, line: int, col: int, snippet: str,
) -> str:
    """The diagnostic repair dead-end detection span_hash. From FINAL_PROPOSAL §Method:

        sha256(diag_id || "|" || normalized_file_path || "|" ||
               start_byte || "|" || end_byte || "|" ||
               whitespace_normalized(snippet))

    We approximate (start_byte, end_byte) by (line, col) since the
    verifier records line/col, not byte offsets.
    """
    s = f"{diag_id}|{file}|{line}|{col}|{' '.join(snippet.split())}"
    return hashlib.sha256(s.encode("utf-8")).hexdigest()
