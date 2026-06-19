"""Terminal criterion + edit validity guards."""
from __future__ import annotations

from enum import Enum

from experiments.types import Action


class TerminalReason(str, Enum):
    SUCCESS = "success"
    BUDGET_EXHAUSTED = "budget_exhausted"
    ALL_BRANCHES_DEAD_END = "all_dead_end"
    NO_PROPOSALS = "no_proposals"


def apply_edit(src: str, action: Action) -> str:
    """Apply a line-range replacement. Lines are 1-based, inclusive on both ends."""
    lines = src.splitlines(keepends=True)
    if not (1 <= action.start_line <= action.end_line <= len(lines)):
        # Invalid edit range: return src unchanged. Upstream treats this as no-op.
        return src
    before = "".join(lines[: action.start_line - 1])
    after = "".join(lines[action.end_line:])
    # Preserve trailing newline on the replaced region if the original lines had one.
    had_nl = lines[action.end_line - 1].endswith(("\n", "\r\n"))
    mid = action.replacement
    if had_nl and not mid.endswith(("\n", "\r\n")):
        mid = mid + "\n"
    return before + mid + after


def within_span_window(action: Action, diag_line: int, window_lines: int) -> bool:
    """Reject edits that do not intersect [diag_line - window, diag_line + window]."""
    lo = max(1, diag_line - window_lines)
    hi = diag_line + window_lines
    # Intersection with [start_line, end_line] is non-empty iff start <= hi and end >= lo.
    return action.start_line <= hi and action.end_line >= lo


def is_trivial_deletion(src: str, action: Action) -> bool:
    """True iff the edit deletes at least one non-whitespace line and replaces with nothing.

    The trivial-deletion guard in FINAL_PROPOSAL rejects such edits so the agent
    cannot satisfy the verifier by simply erasing the broken code.
    """
    if action.replacement.strip() != "":
        return False
    lines = src.splitlines()
    if not (1 <= action.start_line <= action.end_line <= len(lines)):
        return False
    for i in range(action.start_line - 1, action.end_line):
        if lines[i].strip() != "":
            return True
    return False
