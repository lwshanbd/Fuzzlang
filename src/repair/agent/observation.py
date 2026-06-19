"""Signal-mode-aware observation builder.

The three-way verifier-signal ablation (FINAL_PROPOSAL Block B2) requires that
the policy receives *only* the fields appropriate to its signal mode:

  - SIGNAL_FULL           {diag_id, diag_name, diag_msg, span snippet, trajectory}
  - SIGNAL_NO_ID          {diag_name, diag_msg, span snippet, trajectory}
  - SIGNAL_NO_STRUCT      {raw_stderr with DiagID lines stripped, span snippet}

Enforcement lives here, NOT inside individual policy implementations. The
search loop calls this before every policy invocation and passes only the
redacted dict. This is load-bearing for the causal claim.
"""
from __future__ import annotations

import re
from typing import Any

from foundation.types import (
    SIGNAL_FULL,
    SIGNAL_NO_ID,
    SIGNAL_NO_STRUCT,
    AgentState,
)

_DIAGID_LINE = re.compile(r"^DiagID:\s*\d+\s*$\n?", re.MULTILINE)


def strip_diagid_lines(stderr: str) -> str:
    """Remove Fuzzlang-patched Clang's `DiagID: N` lines so NO_STRUCT cannot peek."""
    return _DIAGID_LINE.sub("", stderr)


def build_observation(
    state: AgentState, raw_stderr: str, signal_mode: str
) -> dict[str, Any]:
    """Produce the redacted observation the policy is allowed to see."""
    if signal_mode == SIGNAL_FULL:
        return {
            "mode": SIGNAL_FULL,
            "src": state.src,
            "diag_id": state.diag.diag_id,
            "diag_name": state.diag.diag_name,
            "diag_msg": state.diag.diag_msg,
            "line": state.diag.line,
            "col": state.diag.col,
            "span_snippet": state.diag.span_snippet,
            "trajectory": [(t.diag_id, t.diag_name, t.edit_summary)
                           for t in state.trajectory],
            "turn": state.turn,
        }
    if signal_mode == SIGNAL_NO_ID:
        return {
            "mode": SIGNAL_NO_ID,
            "src": state.src,
            "diag_id": None,
            "diag_name": state.diag.diag_name,
            "diag_msg": state.diag.diag_msg,
            "line": state.diag.line,
            "col": state.diag.col,
            "span_snippet": state.diag.span_snippet,
            "trajectory": [(None, t.diag_name, t.edit_summary)
                           for t in state.trajectory],
            "turn": state.turn,
        }
    if signal_mode == SIGNAL_NO_STRUCT:
        # The policy sees ONLY the raw stderr (with DiagID lines stripped) and
        # the full source. It must parse the offending line, column, span, and
        # any other context from the stderr text itself — just as a stock stderr
        # baseline would. We deliberately do NOT expose `line`, `col`, or any
        # parsed field here; doing so would leak structured compiler output
        # back into the "unstructured" ablation and weaken the causal isolation.
        return {
            "mode": SIGNAL_NO_STRUCT,
            "src": state.src,
            "raw_stderr": strip_diagid_lines(raw_stderr),
            "turn": state.turn,
        }
    raise ValueError(f"unknown signal mode: {signal_mode!r}")
