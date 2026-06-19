"""Tests for the OpenAI-compatible LLM policy: prompt rendering + JSON parsing.

These tests do NOT contact any real server; they use MockChatBackend to inject
scripted responses. The real OpenAIChatBackend is exercised only under the
integration tests (marked, not run here).
"""
from __future__ import annotations

from repair.agent.chat_backend import ChatResponse, MockChatBackend
from repair.agent.policy_base import PolicyContext
from repair.agent.policy_llm import (
    OpenAICompatPolicy,
    _build_messages,
    _parse_edit,
)
from foundation.types import (
    SIGNAL_FULL,
    SIGNAL_NO_ID,
    SIGNAL_NO_STRUCT,
)


# ---- JSON parsing ----

def test_parse_edit_well_formed_json():
    a = _parse_edit('{"start_line": 2, "end_line": 2, "replacement": "int x = 1;"}')
    assert a is not None
    assert a.start_line == 2 and a.end_line == 2 and a.replacement == "int x = 1;"


def test_parse_edit_extracts_from_prose_wrapper():
    text = (
        "Sure! Here is the fix:\n"
        '{"start_line": 3, "end_line": 3, "replacement": "return 0;"}\n'
        "Let me know if you need anything else."
    )
    a = _parse_edit(text)
    assert a is not None
    assert a.start_line == 3


def test_parse_edit_rejects_missing_field():
    assert _parse_edit('{"start_line": 2, "end_line": 2}') is None


def test_parse_edit_rejects_inverted_range():
    assert _parse_edit('{"start_line": 5, "end_line": 2, "replacement": "x"}') is None


def test_parse_edit_rejects_invalid_types():
    assert _parse_edit('{"start_line": "two", "end_line": 2, "replacement": "x"}') is None


def test_parse_edit_rejects_non_json():
    assert _parse_edit("I cannot fix this.") is None


# ---- Prompt rendering per signal mode ----

def _obs_full():
    return {
        "mode": SIGNAL_FULL,
        "src": "int main(){\n int x = 1\n return 0;\n}\n",
        "diag_id": 1001,
        "diag_name": "err_expected_semi",
        "diag_msg": "expected ';'",
        "line": 2,
        "col": 10,
        "span_snippet": " int x = 1",
        "trajectory": [],
        "turn": 0,
    }


def test_full_prompt_includes_diag_id():
    msgs = _build_messages(_obs_full())
    user = msgs[1]["content"]
    assert "1001" in user
    assert "err_expected_semi" in user


def test_no_id_prompt_hides_diag_id_but_keeps_name():
    obs = _obs_full()
    obs["mode"] = SIGNAL_NO_ID
    obs["diag_id"] = None
    msgs = _build_messages(obs)
    user = msgs[1]["content"]
    assert "err_expected_semi" in user
    # The integer ID is not hardcoded; ensure the prompt does not carry the
    # ID explicitly (policy-base observation has diag_id=None in this mode).
    assert "diag_id:" not in user


def test_no_structure_prompt_has_only_stderr_and_src():
    obs = {
        "mode": SIGNAL_NO_STRUCT,
        "src": "int main(){int x=1 return 0;}",
        "raw_stderr": "/p/a.c:1:15: error: expected ';'",
        "turn": 0,
    }
    msgs = _build_messages(obs)
    user = msgs[1]["content"]
    # The prompt MUST NOT contain the typed fields.
    assert "diag_id" not in user
    assert "diag_name" not in user
    assert "err_expected_semi" not in user
    # But the stderr + src should be present.
    assert "error: expected ';'" in user
    assert "int main()" in user


# ---- End-to-end with MockChatBackend ----

def test_policy_parses_k_responses_and_sums_tokens():
    backend = MockChatBackend([
        [
            ChatResponse(text='{"start_line":2,"end_line":2,"replacement":"int x = 1;"}',
                         output_tokens=20),
            ChatResponse(text='not-json', output_tokens=18),
            ChatResponse(text='{"start_line":2,"end_line":2,"replacement":"int x = 1 ;"}',
                         output_tokens=22),
        ]
    ])
    policy = OpenAICompatPolicy(backend)
    ctx = PolicyContext(signal_mode=SIGNAL_FULL, k_proposals=3, temperature=0.7,
                        max_tokens_per_call=128)
    pr = policy.propose_edits(_obs_full(), ctx)
    # Two of three are valid JSON -> two proposals.
    assert len(pr.proposals) == 2
    # Tokens summed over all responses, parse failures included.
    assert pr.tokens_used == 60
    # Verify backend received the expected request.
    assert backend.call_log[0]["n"] == 3
    assert backend.call_log[0]["temperature"] == 0.7
    assert backend.call_log[0]["max_tokens"] == 128
    assert backend.call_log[0]["response_format"]["type"] == "json_schema"
