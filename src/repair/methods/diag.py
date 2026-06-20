"""diagnostic repair: the method. Also serves as the template for diagnostic repair−id / −structure / −loop."""
from __future__ import annotations

from collections.abc import Callable

from repair.agent.policy_base import Policy, PolicyContext
from repair.loop.search import RunResult, run_repair_loop
from foundation.types import SIGNAL_FULL
from foundation.verifier.base import BaseVerifier


def make_diag_runner(
    verifier: BaseVerifier,
    policy: Policy,
    *,
    signal_mode: str = SIGNAL_FULL,
    T: int = 5,
    K: int = 4,
    span_window_lines: int = 5,
    trajectory_window: int = 2,
    temperature: float = 0.8,
    max_tokens_per_call: int = 256,
) -> Callable[[str, list[str]], RunResult]:
    """Bind (verifier, policy, knobs) into a single-argument runner.

    The returned callable takes (source, compile_cmd) and runs one diagnostic repair instance.
    Ablation variants are constructed by varying signal_mode (no_id / no_structure)
    or forcing T=1 (−loop). No special code path per ablation; the signal mode
    only changes what the policy sees when assembling its prompt.
    """
    ctx = PolicyContext(
        signal_mode=signal_mode,
        span_window_lines=span_window_lines,
        trajectory_window=trajectory_window,
        k_proposals=K,
        temperature=temperature,
        max_tokens_per_call=max_tokens_per_call,
    )

    def run(source: str, compile_cmd: list[str]) -> RunResult:
        return run_repair_loop(source, compile_cmd, verifier, policy, ctx, T=T, K=K)

    return run
