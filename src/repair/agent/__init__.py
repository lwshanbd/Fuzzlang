"""Policies: observation -> Action. The LLM-callers live here."""
from repair.agent.chat_backend import (
    ChatBackend,
    ChatResponse,
    MockChatBackend,
    OpenAIChatBackend,
)
from repair.agent.observation import (
    build_observation,
    strip_diagid_lines,
)
from repair.agent.policy_base import (
    EditProposal,
    Policy,
    PolicyContext,
    PolicyResult,
)
from repair.agent.policy_llm import OpenAICompatPolicy
from repair.agent.policy_stub import NoOpPolicy, StubSemicolonPolicy

__all__ = [
    "build_observation",
    "strip_diagid_lines",
    "ChatBackend",
    "ChatResponse",
    "MockChatBackend",
    "OpenAIChatBackend",
    "EditProposal",
    "NoOpPolicy",
    "OpenAICompatPolicy",
    "Policy",
    "PolicyContext",
    "PolicyResult",
    "StubSemicolonPolicy",
]
