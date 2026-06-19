"""Core dataclasses for DVCR: state, action, diagnostic, verifier result.

Every component of the method (verifier, policy, search, terminal) communicates
through these types. Keep this file small and stable — other modules depend on
the exact field names.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class DiagInfo:
    """The primary diagnostic extracted from a compiler invocation.

    Following the FINAL_PROPOSAL primary-diagnostic-only rule: only the first
    `error:` record is represented. Attached notes / macro-expansion /
    template-instantiation traces are dropped.
    """

    diag_id: Optional[int]          # Fuzzlang-modified Clang emits this; None under stock Clang.
    diag_name: Optional[str]        # e.g. "err_expected_semi"; None if unavailable.
    diag_msg: str                   # user-visible diagnostic text, single line.
    file: str                       # normalized source path.
    line: int                       # 1-based line number.
    col: int                        # 1-based column.
    start_byte: int                 # 0-based byte offset into file (after macro expansion).
    end_byte: int                   # exclusive.
    span_snippet: str               # source text between [start_byte, end_byte).

    def span_hash(self) -> str:
        """sha256 of (diag_id, normalized file path, byte range, whitespace-normalized snippet).

        Used for dead-end detection across branches. Byte-level, not AST-normalized
        — AST normalization is fragile on invalid syntax, which is exactly the regime
        we operate in.
        """
        ws_norm = " ".join(self.span_snippet.split())
        h = hashlib.sha256()
        h.update(b"%d|" % (self.diag_id if self.diag_id is not None else -1))
        h.update(self.file.encode() + b"|")
        h.update(b"%d|" % self.start_byte)
        h.update(b"%d|" % self.end_byte)
        h.update(ws_norm.encode())
        return h.hexdigest()


@dataclass(frozen=True)
class VerifierResult:
    """Output of one compile-verify call."""

    ok: bool                        # True iff the file compiles cleanly under the original cmd.
    diag: Optional[DiagInfo]        # None iff ok; else the primary diagnostic.
    raw_stderr: str                 # full stderr, used by the stderr-text baselines.


@dataclass(frozen=True)
class Action:
    """A localized line-range edit. Enforced via JSON schema in the policy prompt."""

    start_line: int                 # 1-based, inclusive.
    end_line: int                   # 1-based, inclusive.
    replacement: str                # may be empty (deletion); triggers trivial-deletion guard.


@dataclass
class TurnRecord:
    """One step of a branch's history; fed back into the policy prompt compactly."""

    diag_id: Optional[int]
    diag_name: Optional[str]
    edit_summary: str               # brief textual summary of the edit the agent applied.


@dataclass
class AgentState:
    """The observation the policy sees. Shape is fixed by the SignalMode variant in use."""

    src: str                        # current full source.
    diag: DiagInfo                  # primary diagnostic at current turn.
    trajectory: list[TurnRecord] = field(default_factory=list)  # last L turns only; trim upstream.
    turn: int = 0                   # 0-based turn index within the branch.


# ---- Signal modes for the causal ablation ----
# DVCR paper's three-way verifier-signal ablation lives here. See FINAL_PROPOSAL Block B2.

SIGNAL_FULL = "full"                # {diag_id, diag_name, diag_msg, span}
SIGNAL_NO_ID = "no_id"              # {diag_name, diag_msg, span}  — structure without ID
SIGNAL_NO_STRUCT = "no_structure"   # raw stderr text
VALID_SIGNALS = (SIGNAL_FULL, SIGNAL_NO_ID, SIGNAL_NO_STRUCT)
