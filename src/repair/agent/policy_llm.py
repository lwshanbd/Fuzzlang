"""Real-LLM policy over an OpenAI-compatible chat backend.

The policy's single job: render a signal-mode-appropriate prompt, call the
backend with JSON-schema-constrained output, and parse the returned edits
into EditProposal objects.

Prompt rendering is deterministic and mode-specific:
  - SIGNAL_FULL:        prompt includes diag_id, diag_name, diag_msg, span snippet.
  - SIGNAL_NO_ID:       prompt includes diag_name, diag_msg, span snippet.
  - SIGNAL_NO_STRUCT:   prompt includes raw stderr (DiagID stripped) + full src.

All three modes share the same JSON-schema output constraint:
    {start_line: int, end_line: int, replacement: str}
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from repair.agent.chat_backend import ChatBackend, ChatResponse
from repair.agent.policy_base import (
    EditProposal,
    Policy,
    PolicyContext,
    PolicyResult,
)
from foundation.types import (
    SIGNAL_FULL,
    SIGNAL_NO_ID,
    SIGNAL_NO_STRUCT,
    Action,
)

_EDIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "start_line": {"type": "integer", "minimum": 1},
        "end_line": {"type": "integer", "minimum": 1},
        "replacement": {"type": "string"},
    },
    "required": ["start_line", "end_line", "replacement"],
    "additionalProperties": False,
}

_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "diag_edit",
        "schema": _EDIT_SCHEMA,
        "strict": True,
    },
}

_SYSTEM = (
    "You are a meticulous C/C++ programmer. Given a buggy source file and a "
    "compiler diagnostic, propose ONE localized edit that, if applied, would "
    "make the file compile. Always emit valid JSON matching the provided schema "
    "with fields start_line, end_line, replacement. Keep the edit minimal: "
    "prefer the smallest replacement that fixes the diagnostic without "
    "introducing new errors. Do not delete non-trivial lines."
)


def _render_source_with_line_numbers(src: str) -> str:
    """Prefix each line with its 1-based index so the model can reference it."""
    return "\n".join(f"{i:4d}| {ln}" for i, ln in enumerate(src.splitlines(), start=1))


def _full_prompt(obs: dict[str, Any]) -> str:
    return (
        "Compiler diagnostic:\n"
        f"  diag_id:   {obs['diag_id']}\n"
        f"  diag_name: {obs['diag_name']}\n"
        f"  diag_msg:  {obs['diag_msg']}\n"
        f"  location:  line {obs['line']}, col {obs['col']}\n"
        f"Offending line ({obs['line']}):\n"
        f"  {obs['span_snippet']}\n\n"
        f"Prior attempts (most recent last):\n"
        f"  {_format_trajectory(obs.get('trajectory', []))}\n\n"
        f"Full source:\n"
        f"```\n{_render_source_with_line_numbers(obs['src'])}\n```\n\n"
        "Propose one localized edit as JSON."
    )


def _no_id_prompt(obs: dict[str, Any]) -> str:
    return (
        "Compiler diagnostic:\n"
        f"  diag_name: {obs['diag_name']}\n"
        f"  diag_msg:  {obs['diag_msg']}\n"
        f"  location:  line {obs['line']}, col {obs['col']}\n"
        f"Offending line ({obs['line']}):\n"
        f"  {obs['span_snippet']}\n\n"
        f"Prior attempts (most recent last):\n"
        f"  {_format_trajectory(obs.get('trajectory', []))}\n\n"
        f"Full source:\n"
        f"```\n{_render_source_with_line_numbers(obs['src'])}\n```\n\n"
        "Propose one localized edit as JSON."
    )


def _no_struct_prompt(obs: dict[str, Any]) -> str:
    """No structured compiler fields available. Model must parse stderr itself."""
    return (
        "Raw compiler stderr:\n"
        f"```\n{obs['raw_stderr']}\n```\n\n"
        f"Full source:\n"
        f"```\n{_render_source_with_line_numbers(obs['src'])}\n```\n\n"
        "Identify the error, then propose one localized edit as JSON."
    )


def _format_trajectory(traj: list[tuple]) -> str:
    if not traj:
        return "(none)"
    parts = []
    for t in traj:
        if len(t) == 3 and t[1] is not None:
            diag_id, diag_name, edit_summary = t
            parts.append(
                f"tried fix for {diag_name or diag_id}: "
                f"{edit_summary!r}; error persisted."
            )
        else:
            parts.append(f"tried {t[-1]!r}; error persisted.")
    return "\n  ".join(parts)


def _build_messages(obs: dict[str, Any]) -> list[dict[str, str]]:
    mode = obs["mode"]
    if mode == SIGNAL_FULL:
        user = _full_prompt(obs)
    elif mode == SIGNAL_NO_ID:
        user = _no_id_prompt(obs)
    elif mode == SIGNAL_NO_STRUCT:
        user = _no_struct_prompt(obs)
    else:
        raise ValueError(f"unknown signal mode: {mode!r}")
    return [{"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user}]


# Fallback parser for servers that ignore json_schema constraint and return plain text.
_JSON_FENCE = re.compile(r"\{[^{}]*\}", re.DOTALL)


def _parse_edit(text: str) -> Optional[Action]:
    """Parse an Action from the model's text. Returns None if malformed."""
    s = text.strip()
    # Try direct JSON parse first.
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        # Fallback: locate the first {...} block.
        m = _JSON_FENCE.search(s)
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None

    if not isinstance(obj, dict):
        return None
    try:
        start = int(obj["start_line"])
        end = int(obj["end_line"])
        repl = str(obj["replacement"])
    except (KeyError, TypeError, ValueError):
        return None
    if start < 1 or end < start:
        return None
    return Action(start_line=start, end_line=end, replacement=repl)


class OpenAICompatPolicy(Policy):
    """Uses an OpenAI-compatible chat backend to generate K parallel edit proposals."""

    def __init__(self, backend: ChatBackend):
        self.backend = backend

    def propose_edits(
        self, observation: dict[str, Any], ctx: PolicyContext
    ) -> PolicyResult:
        messages = _build_messages(observation)
        responses: list[ChatResponse] = self.backend.chat(
            messages=messages,
            temperature=ctx.temperature,
            max_tokens=ctx.max_tokens_per_call,
            n=ctx.k_proposals,
            response_format=_RESPONSE_FORMAT,
        )
        proposals: list[EditProposal] = []
        total_tokens = 0
        for r in responses:
            total_tokens += r.output_tokens
            action = _parse_edit(r.text)
            if action is None:
                continue
            proposals.append(EditProposal(
                action=action,
                edit_summary=f"replace L{action.start_line}-L{action.end_line} "
                             f"({len(action.replacement)}ch)",
            ))
        return PolicyResult(proposals=proposals, tokens_used=total_tokens)
