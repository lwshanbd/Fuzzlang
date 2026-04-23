"""Abstract Verifier. Concrete backends return a VerifierResult for (source, cmd)."""
from __future__ import annotations

from abc import ABC, abstractmethod

from experiments.types import VerifierResult


class BaseVerifier(ABC):
    @abstractmethod
    def verify(
        self,
        source: str,
        compile_cmd: list[str],
        *,
        logical_path: str,
    ) -> VerifierResult:
        """Compile `source` under `compile_cmd` (which references a placeholder path).

        The `logical_path` is what the returned `DiagInfo.file` is populated with.
        This is CRITICAL: it must be stable across repeated calls for the same
        instance, so that `DiagInfo.span_hash()` is deterministic and the
        dead-end detection in the search loop actually detects repeated states.
        It must NOT be the ephemeral tempfile path used at verify time.
        """


PLACEHOLDER = "__SRC__"
"""Compile-cmd placeholder token. Replaced with a temp path per verify() call."""
