"""Signal-mode observation redaction tests.

Ensures DVCR−id cannot see diag_id; DVCR−structure cannot see DiagID lines
AND cannot see any parsed structured field (e.g. `line`).
"""
from __future__ import annotations

from repair.agent.observation import build_observation, strip_diagid_lines
from foundation.types import (
    SIGNAL_FULL,
    SIGNAL_NO_ID,
    SIGNAL_NO_STRUCT,
    AgentState,
    DiagInfo,
    TurnRecord,
)


def _state() -> AgentState:
    return AgentState(
        src="int x = 1\n",
        diag=DiagInfo(
            diag_id=123,
            diag_name="err_expected_semi",
            diag_msg="expected ';'",
            file="/proj/a.c",
            line=1,
            col=10,
            start_byte=0,
            end_byte=9,
            span_snippet="int x = 1",
        ),
        trajectory=[TurnRecord(diag_id=999, diag_name="err_prev", edit_summary="prior")],
        turn=1,
    )


def test_full_exposes_id_and_name_and_trajectory():
    obs = build_observation(_state(), "stderr-body\nDiagID: 123\n", SIGNAL_FULL)
    assert obs["diag_id"] == 123
    assert obs["diag_name"] == "err_expected_semi"
    assert obs["diag_msg"] == "expected ';'"
    assert obs["trajectory"] == [(999, "err_prev", "prior")]


def test_no_id_hides_diag_id_but_keeps_structure():
    obs = build_observation(_state(), "stderr-body\nDiagID: 123\n", SIGNAL_NO_ID)
    assert obs["diag_id"] is None
    assert obs["diag_name"] == "err_expected_semi"
    assert obs["diag_msg"] == "expected ';'"
    # Trajectory must also have diag_ids scrubbed.
    assert obs["trajectory"] == [(None, "err_prev", "prior")]


def test_no_structure_returns_only_src_and_raw_stderr():
    """The no-structure ablation must NOT leak any parsed compiler field.
    Only `src`, `raw_stderr` (DiagID-stripped), `mode`, `turn` allowed."""
    raw = "/p/a.c:1:10: error: expected ';'\nDiagID: 123\n  int x = 1\n             ^\n"
    obs = build_observation(_state(), raw, SIGNAL_NO_STRUCT)
    # Forbidden fields absent.
    for k in ("diag_id", "diag_name", "diag_msg", "line", "col",
              "span_snippet", "trajectory"):
        assert k not in obs, f"SIGNAL_NO_STRUCT leaked field {k!r}"
    # Allowed fields present.
    assert obs["mode"] == "no_structure"
    assert "src" in obs
    assert "raw_stderr" in obs
    assert "turn" in obs
    # DiagID emission stripped so the policy cannot peek at the structured ID.
    assert "DiagID:" not in obs["raw_stderr"]
    # But the rest of stderr (header + body) remains.
    assert "error: expected" in obs["raw_stderr"]


def test_strip_diagid_lines_handles_multiple_and_whitespace():
    s = "a\nDiagID: 1\nb\nDiagID:   42   \nc\n"
    out = strip_diagid_lines(s)
    assert "DiagID" not in out
    assert out == "a\nb\nc\n"


def test_strip_preserves_unrelated_lines_that_mention_diagid_text():
    s = "note: DiagID is cool\nDiagID: 42\ntail\n"
    out = strip_diagid_lines(s)
    assert "note: DiagID is cool" in out
    assert "DiagID: 42" not in out
    assert "tail" in out
