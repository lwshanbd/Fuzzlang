import json

import pytest

from repair.sft_data import (
    LocalizedRepairExample,
    RelativeEdit,
    apply_localized_repair,
    make_localized_repair_example,
    minimal_single_span_edit,
)


def _record(erroneous: str, corrected: str | None) -> dict:
    return {
        "record_id": "record-1",
        "erroneous_src": erroneous,
        "corrected_src": corrected,
        "diagnostics": [
            {
                "diag_id": 123,
                "diag_name": "err_undeclared_var_use",
                "diag_msg": "use of undeclared identifier 'missing'",
                "file": "main.cc",
                "line": 2,
                "col": 10,
                "start_byte": 20,
                "end_byte": 27,
                "span_snippet": "missing",
            }
        ],
        "provenance": {
            "origin": "mutate",
            "source": "project:main.cc",
            "detail": {},
        },
        "split": "train",
        "language": "c++",
    }


def test_minimal_single_span_edit_roundtrips_deletion() -> None:
    erroneous = "int value = total + 1;\n"
    corrected = "int value = total;\n"

    edit = minimal_single_span_edit(erroneous, corrected)

    assert edit == RelativeEdit(start_char=17, end_char=21, replacement="")
    assert edit.apply(erroneous) == corrected


def test_minimal_single_span_edit_covers_multiple_changes() -> None:
    erroneous = "alpha middle omega"
    corrected = "ALPHA middle OMEGA"

    edit = minimal_single_span_edit(erroneous, corrected)

    assert edit.start_char == 0
    assert edit.end_char == len(erroneous)
    assert edit.replacement == corrected
    assert edit.apply(erroneous) == corrected


def test_localized_example_uses_relative_offsets_and_exact_roundtrip() -> None:
    erroneous = "before\nint answer = missing;\nafter\n"
    corrected = "before\nint answer = 42;\nafter\n"

    example = make_localized_repair_example(
        _record(erroneous, corrected), context_lines=0, max_window_chars=100
    )

    assert example.source_window == "int answer = missing;\n"
    assert example.target == RelativeEdit(
        start_char=13, end_char=20, replacement="42"
    )
    assert example.target_json == (
        '{"end_char":20,"replacement":"42","start_char":13}'
    )
    assert apply_localized_repair(erroneous, example) == corrected


def test_localized_example_keeps_configured_context_lines() -> None:
    erroneous = "line 0\nline 1\nbad();\nline 3\nline 4\n"
    corrected = "line 0\nline 1\ngood();\nline 3\nline 4\n"

    example = make_localized_repair_example(
        _record(erroneous, corrected), context_lines=1, max_window_chars=100
    )

    assert example.source_window == "line 1\nbad();\nline 3\n"
    assert example.window_start_char == len("line 0\n")
    assert apply_localized_repair(erroneous, example) == corrected


def test_localized_example_has_diagnostic_and_training_triple() -> None:
    example = make_localized_repair_example(
        _record("int x = missing;\n", "int x = 0;\n"),
        context_lines=0,
        max_window_chars=100,
    )

    triple = example.to_training_example()

    assert triple["record_id"] == "record-1"
    assert triple["source"] == "int x = missing;\n"
    assert triple["error"].startswith(
        "err_undeclared_var_use [DiagID: 123]: use of undeclared identifier"
    )
    assert json.loads(triple["fix"]) == {
        "start_char": 8,
        "end_char": 15,
        "replacement": "0",
    }


def test_localized_example_rejects_missing_corrected_source() -> None:
    with pytest.raises(ValueError, match="corrected_src"):
        make_localized_repair_example(_record("bad", None))


def test_localized_example_rejects_identical_pair() -> None:
    with pytest.raises(ValueError, match="identical"):
        make_localized_repair_example(_record("same", "same"))


def test_localized_example_rejects_oversized_edit() -> None:
    with pytest.raises(ValueError, match="edit exceeds"):
        make_localized_repair_example(
            _record("a" * 30, "b" * 30), max_edit_chars=10
        )


def test_localized_example_rejects_oversized_window() -> None:
    erroneous = "context before\nbad\ncontext after\n"
    corrected = "context before\ngood\ncontext after\n"

    with pytest.raises(ValueError, match="window exceeds"):
        make_localized_repair_example(
            _record(erroneous, corrected),
            context_lines=1,
            max_window_chars=10,
        )


def test_apply_localized_repair_rejects_wrong_source_window() -> None:
    example = LocalizedRepairExample(
        record_id="r",
        source_window="expected",
        diagnostic="error",
        window_start_char=0,
        window_end_char=8,
        target=RelativeEdit(0, 8, "fixed"),
    )

    with pytest.raises(ValueError, match="does not match"):
        apply_localized_repair("different", example)
