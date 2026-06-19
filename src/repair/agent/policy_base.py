"""Abstract Policy: observation -> K candidate edits + token usage.

Signal-mode-aware: observation redaction is enforced UPSTREAM of the policy
by `build_observation` (see observation.py). Policies are passed only the
redacted observation; they do not access `AgentState.diag` directly.
This is load-bearing: without it, the DVCR−id / DVCR−structure ablations
could silently receive the stronger full signal.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from foundation.types import Action, VALID_SIGNALS


@dataclass
class PolicyContext:
    """Runtime config passed to propose_edits on every call."""

    signal_mode: str                # one of SIGNAL_FULL / SIGNAL_NO_ID / SIGNAL_NO_STRUCT
    span_window_lines: int = 5      # L in the paper; edits must intersect [line-L, line+L].
    trajectory_window: int = 2      # last N (diag_id, edit_summary) pairs fed back.
    k_proposals: int = 4            # number of independent edit proposals per turn.
    temperature: float = 0.8        # sampling temp for real LLM policies.
    max_tokens_per_call: int = 256  # per-call output token cap; matched across methods.

    def __post_init__(self) -> None:
        if self.signal_mode not in VALID_SIGNALS:
            raise ValueError(
                f"signal_mode must be one of {VALID_SIGNALS}, got {self.signal_mode}"
            )


@dataclass
class EditProposal:
    action: Action
    edit_summary: str               # short textual description, fed into next-turn trajectory.


@dataclass
class PolicyResult:
    """What a policy returns per call."""

    proposals: list[EditProposal] = field(default_factory=list)
    tokens_used: int = 0            # real LLMs report usage; stubs return 0.


class Policy(ABC):
    @abstractmethod
    def propose_edits(
        self,
        observation: dict[str, Any],
        ctx: PolicyContext,
    ) -> PolicyResult:
        """Return up to ctx.k_proposals candidate edits and the total output tokens used.

        `observation` is the mode-redacted dict produced by `build_observation(...)`.
        The policy MUST use only fields present in `observation`; it has no access
        to the raw AgentState. This enforces the three-way signal ablation boundary.

        Proposals that are schema-invalid or outside the span window should be
        filtered inside the policy (they do not count toward k_proposals).
        """
