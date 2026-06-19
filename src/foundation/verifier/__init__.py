"""Compiler verifiers: maps (source, compile_cmd) -> VerifierResult.

Three backends:
- MockVerifier    — scripted outputs for unit tests (no compiler needed).
- StockClangVerifier — stock Clang; diag_id/diag_name left None.
- FuzzlangClangVerifier — Fuzzlang-modified Clang emitting "DiagID: N" on stderr.

The agent / search loop is indifferent to backend; only VerifierResult matters.
"""
from foundation.verifier.base import BaseVerifier
from foundation.verifier.mock import MockVerifier
from foundation.verifier.stock import StockClangVerifier
from foundation.verifier.fuzzlang import FuzzlangClangVerifier

__all__ = [
    "BaseVerifier",
    "MockVerifier",
    "StockClangVerifier",
    "FuzzlangClangVerifier",
]
