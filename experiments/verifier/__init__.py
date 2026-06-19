"""Compiler verifiers: maps (source, compile_cmd) -> VerifierResult.

Three backends:
- MockVerifier    — scripted outputs for unit tests (no compiler needed).
- StockClangVerifier — stock Clang; diag_id/diag_name left None.
- FuzzlangClangVerifier — Fuzzlang-modified Clang emitting "DiagID: N" on stderr.

The agent / search loop is indifferent to backend; only VerifierResult matters.
"""
from experiments.verifier.base import BaseVerifier
from experiments.verifier.mock import MockVerifier
from experiments.verifier.stock import StockClangVerifier
from experiments.verifier.fuzzlang import FuzzlangClangVerifier

__all__ = [
    "BaseVerifier",
    "MockVerifier",
    "StockClangVerifier",
    "FuzzlangClangVerifier",
]
