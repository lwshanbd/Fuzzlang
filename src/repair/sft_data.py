"""Length-safe SFT representations derived from canonical paired Records.

The localized representation keeps the full canonical pair as the source of
truth but trains a model on a bounded erroneous-source window and one JSON edit
whose character offsets are relative to that window.  The edit is accepted
only when replaying it on the original erroneous source reconstructs the full
``corrected_src`` byte-for-byte at the Python string level.
"""
from __future__ import annotations

import bisect
import json
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class RelativeEdit:
    """A half-open character-range replacement relative to a source window."""

    start_char: int
    end_char: int
    replacement: str

    def __post_init__(self) -> None:
        if self.start_char < 0:
            raise ValueError("start_char must be non-negative")
        if self.end_char < self.start_char:
            raise ValueError("end_char must be at least start_char")

    def apply(self, source: str) -> str:
        if self.end_char > len(source):
            raise ValueError("relative edit lies outside source")
        return source[: self.start_char] + self.replacement + source[self.end_char :]

    def to_dict(self) -> dict[str, int | str]:
        return {
            "start_char": self.start_char,
            "end_char": self.end_char,
            "replacement": self.replacement,
        }


@dataclass(frozen=True)
class LocalizedRepairExample:
    """A bounded prompt window plus its exactly replayable repair target."""

    record_id: str
    source_window: str
    diagnostic: str
    window_start_char: int
    window_end_char: int
    target: RelativeEdit

    @property
    def target_json(self) -> str:
        return json.dumps(
            self.target.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

    def to_training_example(self) -> dict[str, str]:
        return {
            "source": self.source_window,
            "error": self.diagnostic,
            "fix": self.target_json,
            "record_id": self.record_id,
        }


def format_diagnostic(diag: Mapping[str, Any]) -> str:
    """Render a canonical primary diagnostic for a repair prompt."""

    name = diag.get("diag_name")
    diag_id = diag.get("diag_id")
    label_parts: list[str] = []
    if name:
        label_parts.append(str(name))
    if diag_id is not None:
        label_parts.append(f"[DiagID: {diag_id}]")
    label = " ".join(label_parts)
    message = str(diag.get("diag_msg") or "").strip()
    text = f"{label}: {message}" if label and message else label or message

    file = diag.get("file")
    line = diag.get("line")
    col = diag.get("col")
    if file and line is not None and col is not None:
        text += f" ({file}:{line}:{col})"
    return text


def minimal_single_span_edit(erroneous: str, corrected: str) -> RelativeEdit:
    """Return the shortest one-span edit that transforms ``erroneous`` to ``corrected``."""

    if erroneous == corrected:
        raise ValueError("erroneous_src and corrected_src are identical")

    prefix = 0
    common_limit = min(len(erroneous), len(corrected))
    while prefix < common_limit and erroneous[prefix] == corrected[prefix]:
        prefix += 1

    erroneous_end = len(erroneous)
    corrected_end = len(corrected)
    while (
        erroneous_end > prefix
        and corrected_end > prefix
        and erroneous[erroneous_end - 1] == corrected[corrected_end - 1]
    ):
        erroneous_end -= 1
        corrected_end -= 1

    edit = RelativeEdit(
        start_char=prefix,
        end_char=erroneous_end,
        replacement=corrected[prefix:corrected_end],
    )
    if edit.apply(erroneous) != corrected:
        raise ValueError("minimal single-span edit does not roundtrip")
    return edit


def _line_window(
    source: str, edit: RelativeEdit, *, context_lines: int
) -> tuple[int, int]:
    if context_lines < 0:
        raise ValueError("context_lines must be non-negative")

    line_starts = [0]
    line_starts.extend(index + 1 for index, char in enumerate(source) if char == "\n")
    start_line = max(0, bisect.bisect_right(line_starts, edit.start_char) - 1)
    anchor = edit.end_char - 1 if edit.end_char > edit.start_char else edit.start_char
    anchor = min(anchor, len(source))
    end_line = max(0, bisect.bisect_right(line_starts, anchor) - 1)

    first_line = max(0, start_line - context_lines)
    after_last_line = min(len(line_starts), end_line + context_lines + 1)
    window_start = line_starts[first_line]
    window_end = (
        line_starts[after_last_line]
        if after_last_line < len(line_starts)
        else len(source)
    )
    return window_start, window_end


def apply_localized_repair(
    erroneous_src: str, example: LocalizedRepairExample
) -> str:
    """Apply a relative target to its original full erroneous source."""

    if not (0 <= example.window_start_char <= example.window_end_char <= len(erroneous_src)):
        raise ValueError("localized window lies outside erroneous source")
    actual_window = erroneous_src[
        example.window_start_char : example.window_end_char
    ]
    if actual_window != example.source_window:
        raise ValueError("localized source window does not match erroneous source")
    if example.target.end_char > len(example.source_window):
        raise ValueError("localized target lies outside source window")

    absolute_edit = RelativeEdit(
        start_char=example.window_start_char + example.target.start_char,
        end_char=example.window_start_char + example.target.end_char,
        replacement=example.target.replacement,
    )
    return absolute_edit.apply(erroneous_src)


def make_localized_repair_example(
    row: Mapping[str, Any],
    *,
    context_lines: int = 8,
    max_window_chars: int = 8_000,
    max_edit_chars: int = 2_000,
) -> LocalizedRepairExample:
    """Convert one canonical paired Record mapping into a bounded local repair."""

    erroneous = row.get("erroneous_src")
    corrected = row.get("corrected_src")
    if not isinstance(erroneous, str) or not erroneous:
        raise ValueError("canonical localized SFT row requires erroneous_src")
    if not isinstance(corrected, str) or not corrected:
        raise ValueError("canonical localized SFT row requires corrected_src")
    if max_window_chars <= 0 or max_edit_chars <= 0:
        raise ValueError("window and edit limits must be positive")

    diagnostics = row.get("diagnostics")
    if not isinstance(diagnostics, list) or not diagnostics:
        raise ValueError("canonical localized SFT row requires at least one diagnostic")

    absolute_edit = minimal_single_span_edit(erroneous, corrected)
    edit_size = max(
        absolute_edit.end_char - absolute_edit.start_char,
        len(absolute_edit.replacement),
    )
    if edit_size > max_edit_chars:
        raise ValueError(
            f"single-span edit exceeds max_edit_chars={max_edit_chars}: {edit_size}"
        )

    window_start, window_end = _line_window(
        erroneous, absolute_edit, context_lines=context_lines
    )
    source_window = erroneous[window_start:window_end]
    if len(source_window) > max_window_chars:
        raise ValueError(
            f"source window exceeds max_window_chars={max_window_chars}: "
            f"{len(source_window)}"
        )

    target = RelativeEdit(
        start_char=absolute_edit.start_char - window_start,
        end_char=absolute_edit.end_char - window_start,
        replacement=absolute_edit.replacement,
    )
    example = LocalizedRepairExample(
        record_id=str(row.get("record_id") or ""),
        source_window=source_window,
        diagnostic=format_diagnostic(diagnostics[0]),
        window_start_char=window_start,
        window_end_char=window_end,
        target=target,
    )
    if apply_localized_repair(erroneous, example) != corrected:
        raise ValueError("localized repair does not roundtrip to corrected_src")
    return example
