"""B2: static SFT baseline (Fuzzlang v1 recipe).

LoRA-SFT'd model + single-shot inference. The SFT training itself is external
to this module (scripts/polaris_qsub_sft.sh will produce the adapter weights).
At inference time B2 is just: load the adapter, call once, parse the output.

Interface-wise B2 is identical to B0 — the only difference is the *policy*
(a SFT'd model vs a base model). That asymmetry is represented by the caller
passing a different `policy` instance.
"""
from __future__ import annotations

from collections.abc import Callable

from repair.agent.policy_base import Policy
from repair.loop.search import RunResult
from repair.methods.b0_zero_shot import make_b0_runner
from foundation.verifier.base import BaseVerifier


def make_b2_runner(
    verifier: BaseVerifier,
    sft_policy: Policy,
    *,
    max_tokens_per_call: int = 5120,
    temperature: float = 0.0,
    token_envelope: int | None = None,
) -> Callable[[str, list[str]], RunResult]:
    """B2 = B0's scaffold + a LoRA-SFT'd policy. Caller owns adapter loading."""
    return make_b0_runner(
        verifier, sft_policy,
        max_tokens_per_call=max_tokens_per_call,
        temperature=temperature,
        token_envelope=token_envelope,
    )
