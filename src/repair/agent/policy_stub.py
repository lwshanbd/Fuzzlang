"""Deterministic stub policies for unit tests and the P002 smoke test.

These policies do NOT call any LLM. They are used to prove the verifier →
observation → action → verifier loop is wired correctly, independent of
model quality. Real LLM policies live in policy_vllm.py / policy_openai.py
(to be added when we hit the GPU sweep phase).
"""
from __future__ import annotations

import re
from typing import Any

from repair.agent.policy_base import (
    EditProposal,
    Policy,
    PolicyContext,
    PolicyResult,
)
from foundation.types import Action


class StubSemicolonPolicy(Policy):
    """Appends `;` to the offending line. Fixes only missing-semicolon errors.

    In SIGNAL_FULL / SIGNAL_NO_ID, `observation["line"]` is present.
    In SIGNAL_NO_STRUCT, the policy must parse the line from `raw_stderr` — a
    real LLM baseline would do the same. We keep this stub honest about that.
    """

    _LINE_IN_STDERR = re.compile(
        r":\s*(\d+):\s*\d+:\s*(?:fatal\s+)?error:", re.MULTILINE
    )

    def propose_edits(
        self, observation: dict[str, Any], ctx: PolicyContext
    ) -> PolicyResult:
        src = observation.get("src", "")
        line: int | None = observation.get("line")
        if line is None:
            stderr = observation.get("raw_stderr", "")
            m = self._LINE_IN_STDERR.search(stderr)
            if m:
                line = int(m.group(1))
        if line is None or not (1 <= line <= len(src.splitlines())):
            return PolicyResult()
        src_lines = src.splitlines()
        original = src_lines[line - 1]
        patched = original.rstrip() + ";"
        return PolicyResult(
            proposals=[EditProposal(
                action=Action(start_line=line, end_line=line, replacement=patched),
                edit_summary="append ';' to offending line",
            )],
            tokens_used=0,
        )


class NoOpPolicy(Policy):
    """Never proposes anything. Useful for testing the NO_PROPOSALS / FAIL path."""

    def propose_edits(self, observation, ctx):
        return PolicyResult()
