"""DVCR causal ablations: −id, −structure, −loop.

All three share the DVCR scaffold; they differ only in PolicyContext.signal_mode
and (for −loop) the T parameter. No new code paths in search.py.
"""
from __future__ import annotations

from collections.abc import Callable

from experiments.agent.policy_base import Policy
from experiments.loop.search import RunResult, run_dvcr
from experiments.methods.dvcr import make_dvcr_runner
from experiments.types import SIGNAL_NO_ID, SIGNAL_NO_STRUCT
from experiments.verifier.base import BaseVerifier


def make_dvcr_no_id_runner(
    verifier: BaseVerifier, policy: Policy, **kw
) -> Callable[[str, list[str]], RunResult]:
    """Structure preserved, typed diag_id removed. Tests whether the integer ID
    itself carries causal weight beyond the structured {name, msg, span} bundle."""
    return make_dvcr_runner(verifier, policy, signal_mode=SIGNAL_NO_ID, **kw)


def make_dvcr_no_structure_runner(
    verifier: BaseVerifier, policy: Policy, **kw
) -> Callable[[str, list[str]], RunResult]:
    """Raw stderr only (with DiagID lines stripped). Tests the structured
    interface as a whole. Equivalent to B1 in observation, but retains the
    DVCR loop/search configuration so the only difference is the observation."""
    return make_dvcr_runner(verifier, policy, signal_mode=SIGNAL_NO_STRUCT, **kw)


def make_dvcr_no_loop_runner(
    verifier: BaseVerifier, policy: Policy, *, K: int = 4, **kw
) -> Callable[[str, list[str]], RunResult]:
    """T=1 with K parallel proposals at first turn. Isolates the loop's
    contribution from the verifier-selection-at-first-turn contribution."""
    return make_dvcr_runner(verifier, policy, T=1, K=K, **kw)


def make_dvcr_strict_zero_shot_runner(
    verifier: BaseVerifier, policy: Policy, **kw
) -> Callable[[str, list[str]], RunResult]:
    """T=1, K=1. The tightest single-sample with DVCR's full observation,
    for direct head-to-head against B0 (which uses SIGNAL_NO_STRUCT)."""
    return make_dvcr_runner(verifier, policy, T=1, K=1, **kw)
