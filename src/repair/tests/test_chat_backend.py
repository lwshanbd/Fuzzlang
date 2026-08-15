"""Request-kwarg mapping for OpenAIChatBackend.

OpenAI reasoning models (gpt-5.x, o-series) reject `max_tokens` and require
`max_completion_tokens`; vLLM/other OpenAI-compatible servers use `max_tokens`.
build_chat_kwargs picks the right one by model name.
"""
from __future__ import annotations

from repair.agent.chat_backend import (
    ChatResponse, OpenAIChatBackend, VLLMChatBackend, build_chat_kwargs,
)
import pytest

MSGS = [{"role": "user", "content": "hi"}]


def test_vllm_style_model_uses_max_tokens():
    kw = build_chat_kwargs("Qwen2.5-Coder-7B-Instruct", MSGS,
                           temperature=0.8, max_tokens=256, n=1)
    assert kw["max_tokens"] == 256
    assert "max_completion_tokens" not in kw
    assert kw["temperature"] == 0.8
    assert kw["n"] == 1
    assert kw["messages"] is MSGS
    assert kw["model"] == "Qwen2.5-Coder-7B-Instruct"


def test_gpt5_model_uses_max_completion_tokens():
    kw = build_chat_kwargs("gpt-5.4-mini", MSGS,
                           temperature=0.8, max_tokens=256, n=1)
    assert kw["max_completion_tokens"] == 256
    assert "max_tokens" not in kw


def test_o_series_model_uses_max_completion_tokens():
    kw = build_chat_kwargs("o4-mini", MSGS, temperature=1, max_tokens=100, n=2)
    assert kw["max_completion_tokens"] == 100
    assert "max_tokens" not in kw


def test_response_format_included_only_when_given():
    kw = build_chat_kwargs("gpt-5.4-mini", MSGS, temperature=1, max_tokens=8, n=1)
    assert "response_format" not in kw
    rf = {"type": "json_object"}
    kw2 = build_chat_kwargs("gpt-5.4-mini", MSGS, temperature=1, max_tokens=8,
                            n=1, response_format=rf)
    assert kw2["response_format"] is rf


def test_openai_backend_batch_preserves_input_order(monkeypatch):
    backend = OpenAIChatBackend("gemma-4-31B-it", max_concurrency=3)
    calls: list[str] = []

    def fake_chat(*, messages, **_kwargs):
        marker = messages[0]["content"]
        calls.append(marker)
        return [ChatResponse(marker, 1)]

    monkeypatch.setattr(backend, "chat", fake_chat)
    result = backend.chat_batch(
        messages_batch=[
            [{"role": "user", "content": "zero"}],
            [{"role": "user", "content": "one"}],
            [{"role": "user", "content": "two"}],
        ],
        temperature=0.2,
        max_tokens=64,
    )

    assert [items[0].text for items in result] == ["zero", "one", "two"]
    assert sorted(calls) == ["one", "two", "zero"]


def test_openai_backend_rejects_nonpositive_concurrency():
    with pytest.raises(ValueError, match="positive integer"):
        OpenAIChatBackend("gemma-4-31B-it", max_concurrency=0)


def test_vllm_backend_maps_http_response_and_request_payload(monkeypatch):
    backend = VLLMChatBackend("gemma-4-31B-it", max_concurrency=2)
    payloads = []

    def fake_post(payload):
        payloads.append(payload)
        return {
            "choices": [{"message": {"content": "first"}}, {"message": {"content": "second"}}],
            "usage": {"completion_tokens": 10},
        }

    monkeypatch.setattr(backend, "_post_json", fake_post)
    result = backend.chat(
        messages=MSGS, temperature=0.2, max_tokens=64, n=2,
    )

    assert [item.text for item in result] == ["first", "second"]
    assert [item.output_tokens for item in result] == [5, 5]
    assert payloads[0]["model"] == "gemma-4-31B-it"
    assert payloads[0]["max_tokens"] == 64
