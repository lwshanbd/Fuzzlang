"""Policies: observation -> Action. The LLM-callers live here."""
from experiments.agent.observation import (
    build_observation,
    strip_diagid_lines,
)
from experiments.agent.policy_base import (
    EditProposal,
    Policy,
    PolicyContext,
    PolicyResult,
)
from experiments.agent.policy_stub import NoOpPolicy, StubSemicolonPolicy

__all__ = [
    "build_observation",
    "strip_diagid_lines",
    "EditProposal",
    "NoOpPolicy",
    "Policy",
    "PolicyContext",
    "PolicyResult",
    "StubSemicolonPolicy",
]
