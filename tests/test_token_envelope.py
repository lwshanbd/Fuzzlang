"""Token envelope must be enforced immediately after each policy call, not only
at turn boundaries. A mid-turn call that pushes the counter over the cap must
halt the run before any further policy or verifier work."""
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
from experiments.verifier.mock import MockVerifier, ok_result


class HeavyPolicy(Policy):
    """Each call spends 100 tokens regardless."""

    def propose_edits(self, observation, ctx):
        line = observation.get("line", 1)
        return PolicyResult(
            proposals=[EditProposal(
                action=Action(start_line=line, end_line=line, replacement="x = 0;"),
                edit_summary="edit",
            )],
            tokens_used=100,
        )


def _err_on_line_2() -> VerifierResult:
    snippet = "int x"
    return VerifierResult(
        ok=False,
        diag=DiagInfo(
            diag_id=1, diag_name="err", diag_msg="oops",
            file="/proj/a.c", line=2, col=1,
            start_byte=0, end_byte=len(snippet.encode("utf-8")),
            span_snippet=snippet,
        ),
        raw_stderr="/proj/a.c:2:1: error: oops\nDiagID: 1\n",
    )


def test_token_envelope_aborts_on_first_policy_call_that_exceeds_cap():
    """Envelope=50 means the FIRST policy call (100 tokens) immediately over-budgets."""
    v = MockVerifier(lambda src, cmd, logical_path: _err_on_line_2())
    ctx = PolicyContext(signal_mode="full", k_proposals=2)
    result = run_dvcr(
        "line1\nint x\nline3\n", ["clang"],
        v, HeavyPolicy(), ctx, T=10, K=4,
        logical_path="/proj/a.c",
        token_envelope=50,
    )
    assert not result.ok
    assert result.reason == TerminalReason.BUDGET_EXHAUSTED
    # Critically: no verifier calls were made AFTER the envelope trip. Only the
    # INITIAL verify of the source (one call) happened before any policy call.
    assert result.verifier_calls == 1
    assert result.edits_applied == 0
    assert result.output_tokens_used == 100


def test_token_envelope_does_not_trip_when_under_cap():
    """A sufficient envelope lets the loop proceed normally."""

    class OnceThenSuccess(Policy):
        def __init__(self):
            self.n = 0

        def propose_edits(self, observation, ctx):
            self.n += 1
            line = observation.get("line", 2)
            return PolicyResult(
                proposals=[EditProposal(
                    action=Action(start_line=line, end_line=line, replacement="x = 0;"),
                    edit_summary="edit",
                )],
                tokens_used=30,
            )

    def vpolicy(src, cmd, logical_path):
        return ok_result() if "x = 0;" in src else _err_on_line_2()

    v = MockVerifier(vpolicy)
    ctx = PolicyContext(signal_mode="full", k_proposals=2)
    result = run_dvcr(
        "line1\nint x\nline3\n", ["clang"],
        v, OnceThenSuccess(), ctx, T=10, K=4,
        logical_path="/proj/a.c",
        token_envelope=1000,
    )
    assert result.ok
    assert result.reason == TerminalReason.SUCCESS
    assert result.output_tokens_used == 30
