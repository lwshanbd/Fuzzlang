"""Tests for loop/terminal.py: apply_edit, within_span_window, is_trivial_deletion."""
from __future__ import annotations

from experiments.loop.terminal import apply_edit, is_trivial_deletion, within_span_window
from experiments.types import Action


def test_apply_edit_single_line():
    src = "line 1\nline 2\nline 3\n"
    out = apply_edit(src, Action(start_line=2, end_line=2, replacement="replaced"))
    assert out == "line 1\nreplaced\nline 3\n"


def test_apply_edit_range():
    src = "a\nb\nc\nd\n"
    out = apply_edit(src, Action(start_line=2, end_line=3, replacement="X"))
    assert out == "a\nX\nd\n"


def test_apply_edit_preserves_final_newline_absence():
    # If original did not end with a newline, replacement shouldn't force one in.
    src = "only-line"
    out = apply_edit(src, Action(start_line=1, end_line=1, replacement="new"))
    assert out == "new"


def test_apply_edit_invalid_range_is_noop():
    src = "a\nb\n"
    out = apply_edit(src, Action(start_line=5, end_line=5, replacement="X"))
    assert out == src


def test_within_span_window():
    # diag_line=10, window=5 -> valid range [5, 15].
    assert within_span_window(Action(8, 8, "x"), diag_line=10, window_lines=5)
    assert within_span_window(Action(5, 5, "x"), diag_line=10, window_lines=5)
    assert within_span_window(Action(15, 15, "x"), diag_line=10, window_lines=5)
    # Partial overlap is OK.
    assert within_span_window(Action(3, 7, "x"), diag_line=10, window_lines=5)
    # Disjoint is not.
    assert not within_span_window(Action(1, 4, "x"), diag_line=10, window_lines=5)
    assert not within_span_window(Action(16, 20, "x"), diag_line=10, window_lines=5)


def test_trivial_deletion_guard():
    src = "int x;\nint y = 1;\nreturn 0;\n"
    # Empty replacement over a non-whitespace line -> trivial deletion.
    assert is_trivial_deletion(src, Action(2, 2, ""))
    # Empty replacement over whitespace-only span -> NOT trivial (nothing meaningful removed).
    ws_src = "\n\n\n"
    assert not is_trivial_deletion(ws_src, Action(2, 2, ""))
    # Non-empty replacement -> never trivial.
    assert not is_trivial_deletion(src, Action(2, 2, "y = 1;"))
    # Whitespace-only replacement over non-whitespace line -> trivial.
    assert is_trivial_deletion(src, Action(2, 2, "   "))
