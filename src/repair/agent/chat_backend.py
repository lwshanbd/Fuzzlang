"""Chat backend protocol + implementations (mock + OpenAI-compatible).

vLLM, SGLang, llama.cpp, and Ollama all expose the same OpenAI-compatible
/v1/chat/completions endpoint, so `OpenAIChatBackend` is the single real
backend we need. On Polaris we run a vLLM server on a compute node (or the
login-node A100 for sanity) and point this backend at it.

Tests use `MockChatBackend` to inject scripted responses.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
from typing import Any, Optional, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


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
    """Real backend with optional bounded concurrent submission.

    vLLM continuously batches concurrent HTTP requests.  ``chat_batch`` is
    therefore deliberately a client-side concurrency primitive rather than a
    fake prompt-concatenation scheme: it preserves one response group per
    diagnostic while keeping a TP-sharded vLLM server busy.
    """

    def __init__(
        self,
        model_name: str,
        *,
        base_url: str = "http://localhost:8000/v1",
        api_key: str = "dummy",
        timeout_s: float = 120.0,
        max_concurrency: int = 1,
    ):
        if isinstance(max_concurrency, bool) or max_concurrency <= 0:
            raise ValueError("max_concurrency must be a positive integer")
        self.model_name = model_name
        self.base_url = base_url
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.max_concurrency = max_concurrency
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

    def chat_batch(
        self,
        *,
        messages_batch: list[list[dict[str, str]]],
        temperature: float,
        max_tokens: int,
        n: int = 1,
        response_format: Optional[dict[str, Any]] = None,
    ) -> list[list[ChatResponse]]:
        """Submit a bounded batch concurrently and return results in input order.

        This is intended for the local TP=8 vLLM server.  The server, not the
        caller, owns scheduling and dynamic batching across all eight GCDs.
        """
        if not messages_batch:
            return []
        workers = min(self.max_concurrency, len(messages_batch))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(
                    self.chat,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    n=n,
                    response_format=response_format,
                )
                for messages in messages_batch
            ]
            return [future.result() for future in futures]


class VLLMChatBackend:
    """Dependency-free client for the local vLLM OpenAI-compatible endpoint.

    Tioga's Gemma transformers environment intentionally does not depend on
    the external ``openai`` package.  Keeping this client in the standard
    library lets the one-node TP=8 synthesis launcher use that environment
    unchanged.
    """

    def __init__(
        self,
        model_name: str,
        *,
        base_url: str = "http://127.0.0.1:8000/v1",
        timeout_s: float = 120.0,
        max_concurrency: int = 1,
    ) -> None:
        if isinstance(max_concurrency, bool) or max_concurrency <= 0:
            raise ValueError("max_concurrency must be a positive integer")
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.max_concurrency = max_concurrency

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer dummy"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_s) as response:
                decoded = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise RuntimeError(f"vLLM HTTP {error.code}: {error.read().decode('utf-8', 'replace')}") from error
        except (URLError, TimeoutError) as error:
            raise RuntimeError(f"vLLM request failed: {error}") from error
        if not isinstance(decoded, dict):
            raise RuntimeError("vLLM response must be a JSON object")
        return decoded

    def chat(self, *, messages, temperature, max_tokens, n=1, response_format=None):
        payload = build_chat_kwargs(
            self.model_name, messages, temperature=temperature,
            max_tokens=max_tokens, n=n, response_format=response_format,
        )
        response = self._post_json(payload)
        choices = response.get("choices")
        if not isinstance(choices, list):
            raise RuntimeError("vLLM response has no choices list")
        usage = response.get("usage")
        total_out = usage.get("completion_tokens", 0) if isinstance(usage, dict) else 0
        per_choice = total_out // max(1, len(choices))
        result: list[ChatResponse] = []
        for choice in choices:
            if not isinstance(choice, dict):
                raise RuntimeError("vLLM response choice must be an object")
            message = choice.get("message")
            if not isinstance(message, dict):
                raise RuntimeError("vLLM response choice has no message")
            content = message.get("content")
            result.append(ChatResponse(
                text=content if isinstance(content, str) else "",
                output_tokens=per_choice,
            ))
        return result

    def chat_batch(
        self,
        *,
        messages_batch: list[list[dict[str, str]]],
        temperature: float,
        max_tokens: int,
        n: int = 1,
        response_format: Optional[dict[str, Any]] = None,
    ) -> list[list[ChatResponse]]:
        if not messages_batch:
            return []
        workers = min(self.max_concurrency, len(messages_batch))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(
                    self.chat,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    n=n,
                    response_format=response_format,
                )
                for messages in messages_batch
            ]
            return [future.result() for future in futures]
