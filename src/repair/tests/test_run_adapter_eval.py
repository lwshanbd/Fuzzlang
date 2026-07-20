import json

import pytest

from repair import run_adapter_eval


def _row() -> dict:
    erroneous = "before\nint value = missing;\nafter\n"
    corrected = "before\nint value = 0;\nafter\n"
    return {
        "record_id": "heldout-1",
        "erroneous_src": erroneous,
        "corrected_src": corrected,
        "diagnostics": [
            {
                "diag_id": 123,
                "diag_name": "err_undeclared_var_use",
                "diag_msg": "use of undeclared identifier 'missing'",
                "file": "main.cc",
                "line": 2,
                "col": 13,
            }
        ],
        "provenance": {
            "origin": "mutate",
            "source": "project:main.cc",
            "detail": {
                "compile_cmd": ["__CLANG__", "-fsyntax-only", "__SRC__"],
                "source_path": "src/main.cc",
            },
        },
        "split": "eval",
        "language": "c++",
    }


def test_parse_relative_edit_accepts_fenced_json_with_surrounding_text() -> None:
    text = (
        "Here is the edit:\n```json\n"
        '{"start_char": 19, "end_char": 26, "replacement": "0"}'
        "\n```"
    )

    edit = run_adapter_eval.parse_relative_edit(text)

    assert edit.start_char == 19
    assert edit.end_char == 26
    assert edit.replacement == "0"


@pytest.mark.parametrize(
    "text,match",
    [
        ('{"start_char": 1, "end_char": 2}', "exactly"),
        ('{"start_char": true, "end_char": 2, "replacement": "x"}', "integers"),
        ('{"start_char": 3, "end_char": 2, "replacement": "x"}', "at least"),
        ("no object", "JSON object"),
    ],
)
def test_parse_relative_edit_rejects_invalid_outputs(text: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        run_adapter_eval.parse_relative_edit(text)


def test_apply_model_edit_reconstructs_complete_corrected_source() -> None:
    row = _row()
    example = run_adapter_eval.make_localized_repair_example(row, context_lines=0)

    predicted = run_adapter_eval.apply_model_edit(
        row, example.target_json, context_lines=0
    )

    assert predicted == row["corrected_src"]


def test_apply_window_rewrite_reconstructs_complete_corrected_source() -> None:
    row = _row()
    response = json.dumps({"corrected_window": "int value = 0;\n"})

    predicted = run_adapter_eval.apply_model_edit(
        row,
        response,
        target_format="window-rewrite",
        context_lines=0,
    )

    assert predicted == row["corrected_src"]


def test_parse_window_rewrite_requires_exact_string_field() -> None:
    assert run_adapter_eval.parse_window_rewrite(
        'prefix {"corrected_window":"int x = 0;\\n"}'
    ) == "int x = 0;\n"
    with pytest.raises(ValueError, match="exactly"):
        run_adapter_eval.parse_window_rewrite(
            '{"corrected_window":"x","extra":1}'
        )


def test_summarize_counts_parse_compile_and_exact_rates() -> None:
    results = [
        {"parse_ok": True, "compile_ok": True, "exact_match": True},
        {"parse_ok": True, "compile_ok": False, "exact_match": False},
        {"parse_ok": False, "compile_ok": False, "exact_match": False},
    ]

    summary = run_adapter_eval.summarize_results(results)

    assert summary == {
        "n": 3,
        "eligible": 3,
        "eligible_compile_ok": 1,
        "eligible_exact_match": 1,
        "parse_ok": 2,
        "parse_rate": pytest.approx(2 / 3),
        "compile_ok": 1,
        "verified_fix_rate": pytest.approx(1 / 3),
        "verified_fix_rate_eligible": pytest.approx(1 / 3),
        "exact_match": 1,
        "exact_match_rate": pytest.approx(1 / 3),
        "exact_match_rate_eligible": pytest.approx(1 / 3),
    }


def test_summarize_excludes_stale_ground_truth_from_eligible_rates() -> None:
    results = [
        {
            "ground_truth_ok": True,
            "parse_ok": True,
            "compile_ok": True,
            "exact_match": True,
        },
        {
            "ground_truth_ok": False,
            "parse_ok": True,
            "compile_ok": False,
            "exact_match": False,
        },
    ]

    summary = run_adapter_eval.summarize_results(results)

    assert summary["eligible"] == 1
    assert summary["eligible_compile_ok"] == 1
    assert summary["eligible_exact_match"] == 1
    assert summary["verified_fix_rate"] == pytest.approx(0.5)
    assert summary["verified_fix_rate_eligible"] == pytest.approx(1.0)


def test_load_rows_is_deterministic_and_bounded(tmp_path) -> None:
    path = tmp_path / "eval.jsonl"
    path.write_text("".join(json.dumps(_row() | {"record_id": str(i)}) + "\n" for i in range(5)))

    rows = run_adapter_eval.load_rows(path, max_instances=3)

    assert [row["record_id"] for row in rows] == ["0", "1", "2"]


def test_adapter_is_optional_for_base_model_control() -> None:
    args = run_adapter_eval._parse_args(
        [
            "--base-model", "gemma",
            "--data-path", "eval.jsonl",
            "--clang-bin", "clang++",
            "--clang-c-bin", "clang",
            "--diagtool-bin", "diagtool",
            "--out", "base.json",
        ]
    )

    assert args.adapter is None
    assert args.clang_c_bin == "clang"
