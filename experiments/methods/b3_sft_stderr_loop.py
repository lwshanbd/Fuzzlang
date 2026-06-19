"""B3 (appendix safety): SFT + stderr-loop.

In case reviewers insist on the "obvious stronger baseline" (Fuzzlang-SFT
*plus* iterative feedback), we pre-run this: same loop as B1, but the policy
is the LoRA-SFT'd model rather than the base model. Lives in the appendix.
"""
from __future__ import annotations

from collections.abc import Callable

from experiments.agent.policy_base import Policy
from experiments.loop.search import RunResult
from experiments.methods.b1_stderr_loop import make_b1_runner
from experiments.verifier.base import BaseVerifier


def make_b3_runner(
    verifier: BaseVerifier,
    sft_policy: Policy,
    *,
    T: int = 5,
    K: int = 4,
    temperature: float = 0.8,
    max_tokens_per_call: int = 256,
    token_envelope: int | None = None,
) -> Callable[[str, list[str]], RunResult]:
    return make_b1_runner(
        verifier, sft_policy,
        T=T, K=K,
        temperature=temperature,
        max_tokens_per_call=max_tokens_per_call,
        token_envelope=token_envelope,
    )
