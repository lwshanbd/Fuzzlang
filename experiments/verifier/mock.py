"""Scripted verifier for unit tests. Returns whatever the test writer programmed."""
from __future__ import annotations

from collections.abc import Callable

from experiments.types import VerifierResult
from experiments.verifier.base import BaseVerifier


class MockVerifier(BaseVerifier):
    """A verifier whose behavior is a pure function `(source, cmd, logical_path) -> VerifierResult`.

    The test writer supplies `policy`. This enables deterministic end-to-end
    tests of search/terminal/dvcr without requiring a real compiler.
    """

    def __init__(self, policy: Callable[[str, list[str], str], VerifierResult]):
        self._policy = policy
        self.call_log: list[tuple[str, tuple[str, ...], str]] = []

    def verify(
        self,
        source: str,
        compile_cmd: list[str],
        *,
        logical_path: str,
    ) -> VerifierResult:
        self.call_log.append((source, tuple(compile_cmd), logical_path))
        return self._policy(source, compile_cmd, logical_path)


def ok_result(raw_stderr: str = "") -> VerifierResult:
    return VerifierResult(ok=True, diag=None, raw_stderr=raw_stderr)
