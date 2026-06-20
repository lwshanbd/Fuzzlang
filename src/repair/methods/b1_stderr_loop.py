"""B1: Self-Debug-style iterative repair with raw-stderr feedback.

Same loop shape as diagnostic repair (K=4, T=5, parallel sampling, verifier selection),
but the policy observation is SIGNAL_NO_STRUCT — raw stderr only, no typed
diagnostic fields. This is the headline baseline: the diagnostic repair ↔ B1 gap is the
paper's main effect size.
"""
from __future__ import annotations

from collections.abc import Callable

from repair.agent.policy_base import Policy
from repair.loop.search import RunResult, run_repair_loop
from foundation.types import SIGNAL_NO_STRUCT
from foundation.verifier.base import BaseVerifier


def make_b1_runner(
    verifier: BaseVerifier,
    policy: Policy,
    *,
    T: int = 5,
    K: int = 4,
    temperature: float = 0.8,
    max_tokens_per_call: int = 256,
    token_envelope: int | None = None,
) -> Callable[[str, list[str]], RunResult]:
    from repair.agent.policy_base import PolicyContext
    ctx = PolicyContext(
        signal_mode=SIGNAL_NO_STRUCT,
        span_window_lines=5,
        trajectory_window=2,
        k_proposals=K,
        temperature=temperature,
        max_tokens_per_call=max_tokens_per_call,
    )

    def run(source: str, compile_cmd: list[str]) -> RunResult:
        return run_repair_loop(
            source, compile_cmd, verifier, policy, ctx,
            T=T, K=K, token_envelope=token_envelope,
        )

    return run
