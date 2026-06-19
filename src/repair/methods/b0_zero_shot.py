"""B0: zero-shot single-shot baseline.

One LLM call with (buggy_src, compile_cmd, stderr) → full patched source.
No loop, no SFT. Token budget matched to DVCR's envelope in a single call.

Implemented as DVCR with T=1, K=1, SIGNAL_NO_STRUCT. Same scaffold, no
special code path. Matched-budget enforcement uses the same mechanism.
"""
from __future__ import annotations

from collections.abc import Callable

from repair.agent.policy_base import Policy
from repair.loop.search import RunResult, run_dvcr
from repair.methods.dvcr import make_dvcr_runner
from foundation.types import SIGNAL_NO_STRUCT
from foundation.verifier.base import BaseVerifier


def make_b0_runner(
    verifier: BaseVerifier,
    policy: Policy,
    *,
    max_tokens_per_call: int = 5120,   # full envelope in one shot.
    temperature: float = 0.0,          # single-shot; greedy matches "zero-shot".
    token_envelope: int | None = None,
) -> Callable[[str, list[str]], RunResult]:
    """B0: single LLM call, no iteration, raw stderr observation.

    Budget is spent in one call; the envelope is the envelope.
    """
    runner = make_dvcr_runner(
        verifier, policy,
        signal_mode=SIGNAL_NO_STRUCT,
        T=1, K=1,
        span_window_lines=5,
        trajectory_window=0,
        temperature=temperature,
        max_tokens_per_call=max_tokens_per_call,
    )

    def run(source: str, compile_cmd: list[str]) -> RunResult:
        return run_dvcr(
            source, compile_cmd, verifier, policy,
            ctx=_ctx_like(runner, max_tokens_per_call, temperature),
            T=1, K=1, token_envelope=token_envelope,
        )

    return run


def _ctx_like(_runner, max_tokens_per_call, temperature):
    """Build a PolicyContext mirroring what make_dvcr_runner produced."""
    from repair.agent.policy_base import PolicyContext
    return PolicyContext(
        signal_mode=SIGNAL_NO_STRUCT,
        span_window_lines=5,
        trajectory_window=0,
        k_proposals=1,
        temperature=temperature,
        max_tokens_per_call=max_tokens_per_call,
    )
