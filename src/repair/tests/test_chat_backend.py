"""Request-kwarg mapping for OpenAIChatBackend.

OpenAI reasoning models (gpt-5.x, o-series) reject `max_tokens` and require
`max_completion_tokens`; vLLM/other OpenAI-compatible servers use `max_tokens`.
build_chat_kwargs picks the right one by model name.
"""
from __future__ import annotations

from repair.agent.chat_backend import build_chat_kwargs

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
