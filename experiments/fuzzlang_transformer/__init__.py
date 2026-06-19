"""Fuzzlang-Transformer infrastructure for v2 Column A mutation eval.

Two halves:
  1. AST-hash dedup (`ast_hash`) — load-bearing for gate G-M2: every Y eval
     mutation's 5-line AST-normalized hash must NOT collide with any
     X-train mutation hash. Without this, mutation eval can leak.
  2. Pipeline orchestrator (`scripts/run_p009_*`) — drives the existing
     v1 Fuzzlang-Transformer wrapper (`src/wrapper.py`) over the X-train,
     X-dev, and Y file lists produced by P011, then runs dedup.
"""
from experiments.fuzzlang_transformer.ast_hash import (
    five_line_window,
    text_normalized_hash,
    ast_normalized_hash,
    span_hash,
)

__all__ = [
    "five_line_window",
    "text_normalized_hash",
    "ast_normalized_hash",
    "span_hash",
]
