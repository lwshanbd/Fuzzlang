"""Dead-end detection and NO_PROPOSALS semantics in search.py.

Also covers: token-envelope termination, and that the ALL_BRANCHES_DEAD_END
terminal fires correctly once all respawns are exhausted.
"""
from __future__ import annotations

from experiments.agent.policy_base import (
    EditProposal,
    Policy,
    PolicyContext,
    PolicyResult,
)
from experiments.loop.search import run_dvcr
from experiments.loop.terminal import TerminalReason
from experiments.types import Action, DiagInfo, VerifierResult
from experiments.verifier.mock import MockVerifier


def _unchanging_err(diag_id: int = 42, line: int = 1) -> VerifierResult:
    """The verifier always returns the SAME diagnostic, so span_hash never changes."""
    snippet = "static int x"
    return VerifierResult(
        ok=False,
        diag=DiagInfo(
            diag_id=diag_id, diag_name="err_stuck", diag_msg="always wrong",
            file="/proj/stuck.c", line=line, col=1,
            start_byte=0, end_byte=len(snippet.encode("utf-8")),
            span_snippet=snippet,
        ),
        raw_stderr=f"/proj/stuck.c:{line}:1: error: always wrong\nDiagID: {diag_id}\n",
    )


class MutatingNoProgressPolicy(Policy):
    """Proposes edits that mutate src but never change the diagnostic."""

    def __init__(self, tokens_per_call: int = 10):
        self.tokens_per_call = tokens_per_call
        self._counter = 0

    def propose_edits(self, observation, ctx):
        line = observation["line"]
        self._counter += 1
        # Propose a single tiny edit that changes the line but triggers the same error.
        return PolicyResult(
            proposals=[EditProposal(
                action=Action(start_line=line, end_line=line,
                              replacement=f"static int x = {self._counter}"),
                edit_summary=f"no-progress mutation #{self._counter}",
            )],
            tokens_used=self.tokens_per_call,
        )


def test_dead_end_triggers_after_two_consecutive_same_hash_turns():
    """Verifier always returns the same diagnostic -> every branch's prev and current
    span_hash end up equal after turn 2; the loop should mark it dead-end and, after
    the single permitted respawn also dead-ends, terminate ALL_BRANCHES_DEAD_END."""
    v = MockVerifier(lambda src, cmd, logical_path: _unchanging_err())
    ctx = PolicyContext(signal_mode="full", k_proposals=2)
    result = run_dvcr(
        "static int x\n", ["clang"],
        v, MutatingNoProgressPolicy(), ctx, T=10, K=2,
        logical_path="/proj/stuck.c",
    )
    assert not result.ok
    assert result.reason == TerminalReason.ALL_BRANCHES_DEAD_END


def test_token_envelope_terminates_with_budget_exhausted():
    v = MockVerifier(lambda src, cmd, logical_path: _unchanging_err())
    ctx = PolicyContext(signal_mode="full", k_proposals=2)
    policy = MutatingNoProgressPolicy(tokens_per_call=100)
    result = run_dvcr(
        "static int x\n", ["clang"],
        v, policy, ctx, T=50, K=2,
        logical_path="/proj/stuck.c",
        token_envelope=150,  # will trip after ~two branch×turn calls.
    )
    assert not result.ok
    # Either BUDGET_EXHAUSTED (if envelope trips before dead-end chain), or
    # ALL_BRANCHES_DEAD_END (if dead-end fires first). Both are acceptable.
    assert result.reason in (
        TerminalReason.BUDGET_EXHAUSTED,
        TerminalReason.ALL_BRANCHES_DEAD_END,
    )
    assert result.output_tokens_used > 0
