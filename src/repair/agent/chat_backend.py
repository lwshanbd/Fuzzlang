"""Chat backend protocol + implementations (mock + OpenAI-compatible).

vLLM, SGLang, llama.cpp, and Ollama all expose the same OpenAI-compatible
/v1/chat/completions endpoint, so `OpenAIChatBackend` is the single real
backend we need. On Polaris we run a vLLM server on a compute node (or the
login-node A100 for sanity) and point this backend at it.

Tests use `MockChatBackend` to inject scripted responses.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol


@dataclass(frozen=True)
class ChatResponse:
    text: str
    output_tokens: int


class ChatBackend(Protocol):
    def chat(
        self,
        *,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        n: int = 1,
        response_format: Optional[dict[str, Any]] = None,
    ) -> list[ChatResponse]:
        """Return n candidate completions. `response_format` carries a JSON schema
        the server is asked to constrain output against (OpenAI json_schema shape)."""


class MockChatBackend:
    """Scripted backend for tests. Pops from `scripted_responses` per call."""

    def __init__(self, scripted_responses: list[list[ChatResponse]]):
        self._queue = list(scripted_responses)
        self.call_log: list[dict[str, Any]] = []

    def chat(self, *, messages, temperature, max_tokens, n=1, response_format=None):
        self.call_log.append(
            {"messages": messages, "temperature": temperature,
             "max_tokens": max_tokens, "n": n, "response_format": response_format}
        )
        if not self._queue:
            raise AssertionError("MockChatBackend: scripted_responses exhausted")
        return self._queue.pop(0)


_REASONING_PREFIXES = ("gpt-5", "o1", "o3", "o4")


def build_chat_kwargs(
    model: str,
    messages: list[dict[str, str]],
    *,
    temperature: float,
    max_tokens: int,
    n: int = 1,
    response_format: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Assemble chat.completions kwargs, picking the right token-limit param.

    OpenAI reasoning models (gpt-5.x, o-series) reject `max_tokens` and require
    `max_completion_tokens`; vLLM and other OpenAI-compatible servers use the
    classic `max_tokens`. Select by model name.
    """
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "n": n,
    }
    if model.lower().startswith(_REASONING_PREFIXES):
        kwargs["max_completion_tokens"] = max_tokens
    else:
        kwargs["max_tokens"] = max_tokens
    if response_format is not None:
        kwargs["response_format"] = response_format
    return kwargs


class OpenAIChatBackend:
    """Real backend. Lazy-imports `openai` so unit tests need not install it."""

    def __init__(
        self,
        model_name: str,
        *,
        base_url: str = "http://localhost:8000/v1",
        api_key: str = "dummy",
        timeout_s: float = 120.0,
    ):
        self.model_name = model_name
        self.base_url = base_url
        self.api_key = api_key
        self.timeout_s = timeout_s
        self._client = None

    def _ensure_client(self):
        if self._client is None:
            from openai import OpenAI  # deferred import
            self._client = OpenAI(base_url=self.base_url, api_key=self.api_key,
                                  timeout=self.timeout_s)
        return self._client

    def chat(self, *, messages, temperature, max_tokens, n=1, response_format=None):
        client = self._ensure_client()
        kwargs = build_chat_kwargs(
            self.model_name, messages, temperature=temperature,
            max_tokens=max_tokens, n=n, response_format=response_format,
        )
        resp = client.chat.completions.create(**kwargs)
        out: list[ChatResponse] = []
        # vLLM reports usage at the response level (sum over all choices);
        # we attribute tokens evenly across choices so downstream accounting is
        # per-response rather than per-batch.
        total_out = getattr(resp.usage, "completion_tokens", 0) if resp.usage else 0
        per_choice = total_out // max(1, len(resp.choices))
        for choice in resp.choices:
            out.append(ChatResponse(
                text=choice.message.content or "",
                output_tokens=per_choice,
            ))
        return out
