"""The diagnostic-repair method (and its ablations) must honor the same
`token_envelope` matched-budget cap that b0/b1 do. Regression test for a bug
where `make_diag_runner` silently dropped the envelope, so `diag` ran unbounded
while the baselines were budget-capped — voiding the matched-budget comparison.
"""
from __future__ import annotations

from repair.agent.policy_base import EditProposal, Policy, PolicyResult
from repair.loop.terminal import TerminalReason
from repair.methods import make_diag_runner, make_no_id_runner
from foundation.types import Action, DiagInfo, VerifierResult
from foundation.verifier.mock import MockVerifier


class HeavyPolicy(Policy):
    def propose_edits(self, observation, ctx):
        line = observation.get("line", 1)
        return PolicyResult(
            proposals=[EditProposal(
                action=Action(start_line=line, end_line=line, replacement="x = 0;"),
                edit_summary="edit",
            )],
            tokens_used=100,
        )


def _always_errs(src, cmd, logical_path):
    return VerifierResult(
        ok=False,
        diag=DiagInfo(diag_id=1, diag_name="err", diag_msg="oops",
                      file="/a.c", line=1, col=1, start_byte=0, end_byte=3,
                      span_snippet="int"),
        raw_stderr="/a.c:1:1: error: oops\nDiagID: 1\n",
    )


def test_make_diag_runner_enforces_token_envelope():
    v = MockVerifier(_always_errs)
    runner = make_diag_runner(v, HeavyPolicy(), T=10, K=4, token_envelope=50)
    r = runner("int x\n", ["clang"])
    assert not r.ok
    assert r.reason == TerminalReason.BUDGET_EXHAUSTED
    assert r.output_tokens_used == 100


def test_ablation_runner_accepts_token_envelope():
    v = MockVerifier(_always_errs)
    runner = make_no_id_runner(v, HeavyPolicy(), T=10, K=4, token_envelope=50)
    r = runner("int x\n", ["clang"])
    assert r.reason == TerminalReason.BUDGET_EXHAUSTED
