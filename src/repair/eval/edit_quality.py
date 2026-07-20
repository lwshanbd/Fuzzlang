"""Static edit-quality signals for compiler-clean repair outputs."""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any


def _non_whitespace(text: str) -> int:
    return sum(not char.isspace() for char in text)


def _edit_counts(source: str, predicted: str) -> tuple[int, int, int, int]:
    removed_chars = inserted_chars = 0
    removed_non_whitespace = inserted_non_whitespace = 0
    matcher = SequenceMatcher(None, source, predicted, autojunk=False)
    for tag, source_start, source_end, predicted_start, predicted_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        removed = source[source_start:source_end]
        inserted = predicted[predicted_start:predicted_end]
        removed_chars += len(removed)
        inserted_chars += len(inserted)
        removed_non_whitespace += _non_whitespace(removed)
        inserted_non_whitespace += _non_whitespace(inserted)
    return (
        removed_chars,
        inserted_chars,
        removed_non_whitespace,
        inserted_non_whitespace,
    )


def _changed_line_counts(source: str, predicted: str) -> tuple[int, int]:
    matcher = SequenceMatcher(
        None,
        source.splitlines(keepends=True),
        predicted.splitlines(keepends=True),
        autojunk=False,
    )
    changed_source = changed_predicted = 0
    for tag, source_start, source_end, predicted_start, predicted_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        changed_source += source_end - source_start
        changed_predicted += predicted_end - predicted_start
    return changed_source, changed_predicted


def compute_edit_quality(
    source_window: str,
    predicted_window: str,
    gold_window: str,
) -> dict[str, Any]:
    """Compare one predicted local rewrite with its input and gold rewrite.

    ``large_deletion`` means that at least 20 non-whitespace input characters
    disappear, the prediction retains less than half of the input window, and
    the gold does not make the same deletion. ``excessive_edit`` means the
    character diff is over 20 operations and more than five times the gold
    diff. A pure line deletion removes at least five non-whitespace characters,
    inserts no replacement line, and is absent from gold. These are audit
    flags, not semantic-invalidity judgments.
    """

    removed, inserted, removed_non_ws, inserted_non_ws = _edit_counts(
        source_window, predicted_window
    )
    gold_removed, gold_inserted, gold_removed_non_ws, _ = _edit_counts(
        source_window, gold_window
    )
    changed_source, changed_predicted = _changed_line_counts(
        source_window, predicted_window
    )
    gold_changed_source, gold_changed_predicted = _changed_line_counts(
        source_window, gold_window
    )
    source_non_ws = _non_whitespace(source_window)
    predicted_non_ws = _non_whitespace(predicted_window)
    gold_non_ws = _non_whitespace(gold_window)
    predicted_edit_size = removed + inserted
    gold_edit_size = gold_removed + gold_inserted
    edit_size_ratio = (
        predicted_edit_size / gold_edit_size if gold_edit_size else None
    )
    retained_ratio = (
        (source_non_ws - removed_non_ws) / source_non_ws
        if source_non_ws
        else 1.0
    )
    empty_repair = not predicted_window.strip() and bool(gold_window.strip())
    predicted_large_deletion = (
        removed_non_ws >= 20
        and predicted_non_ws < 0.5 * source_non_ws
    )
    gold_large_deletion = (
        gold_removed_non_ws >= 20
        and gold_non_ws < 0.5 * source_non_ws
    )
    large_deletion = predicted_large_deletion and not gold_large_deletion
    excessive_edit = (
        gold_edit_size > 0
        and predicted_edit_size > 20
        and predicted_edit_size > 5 * gold_edit_size
    )
    predicted_pure_line_deletion = (
        changed_source > 0
        and changed_predicted == 0
        and removed_non_ws >= 5
    )
    gold_pure_line_deletion = (
        gold_changed_source > 0
        and gold_changed_predicted == 0
        and gold_removed_non_ws >= 5
    )
    pure_line_deletion = (
        predicted_pure_line_deletion and not gold_pure_line_deletion
    )
    return {
        "source_window_chars": len(source_window),
        "predicted_window_chars": len(predicted_window),
        "gold_window_chars": len(gold_window),
        "removed_chars": removed,
        "inserted_chars": inserted,
        "removed_non_whitespace": removed_non_ws,
        "inserted_non_whitespace": inserted_non_ws,
        "non_whitespace_retained_ratio": retained_ratio,
        "predicted_edit_size": predicted_edit_size,
        "gold_edit_size": gold_edit_size,
        "edit_size_ratio": edit_size_ratio,
        "changed_original_lines": changed_source,
        "changed_predicted_lines": changed_predicted,
        "empty_repair": empty_repair,
        "large_deletion": large_deletion,
        "excessive_edit": excessive_edit,
        "pure_line_deletion": pure_line_deletion,
        "degenerate": (
            empty_repair or large_deletion or excessive_edit or pure_line_deletion
        ),
    }
