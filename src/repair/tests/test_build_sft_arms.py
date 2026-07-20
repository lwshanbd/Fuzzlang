import json
from pathlib import Path

import pytest

from gen.fuzzlang_dsl import FuzzLangInjector
from repair import build_sft_arms


class FakeTokenizer:
    chat_template = "available"

    def apply_chat_template(self, messages, **kwargs):
        assert kwargs == {"tokenize": False, "add_generation_prompt": False}
        return (
            f"<user>{messages[0]['content']}"
            f"<assistant>{messages[1]['content']}<eot>"
        )

    def __call__(self, text, *, truncation=False):
        assert truncation is False
        return {"input_ids": list(text.encode("utf-8"))}


def _diag(name: str = "err_undeclared_var_use") -> list[dict]:
    return [{
        "diag_id": 17,
        "diag_name": name,
        "diag_msg": "use of undeclared identifier",
        "file": "main.cc",
        "line": 1,
        "col": 22,
        "start_byte": 21,
        "end_byte": 28,
        "span_snippet": "missing",
    }]


def _row(record_id: str, source_key: str, *, method: str) -> dict:
    suffix = record_id.replace("-", "_")
    detail: dict
    origin: str
    if method == "mechanical":
        origin = "mutate"
        detail = {"mutation": "replace_identifier"}
    elif method == "direct_edit":
        origin = "llm"
        detail = {"generator": "llm_localized_edit"}
    elif method == "fuzzlang":
        origin = "mutate"
        detail = {
            "strategy": "learned_recipe_replay",
            "recipe_id": "recipe-test",
        }
    else:
        raise AssertionError(method)
    return {
        "record_id": record_id,
        "erroneous_src": f"int {suffix}() {{ return missing; }}\n",
        "corrected_src": f"int {suffix}() {{ return 0; }}\n",
        "diagnostics": _diag(),
        "provenance": {
            "origin": origin,
            "source": source_key,
            "detail": detail,
        },
        "split": "eval" if method == "fuzzlang" else "train",
        "language": "c++",
    }


def _recipe() -> dict:
    return {
        "recipe_id": "recipe-test",
        "diag_name": "err_undeclared_var_use",
        "language": "c++",
        "operation": "replace",
        "old_patterns": ["<ID0>"],
        "new_text": "missing",
        "left_context": ["return"],
        "right_context": [";"],
        "portable": True,
        "replacement_parts": [["literal", "missing"]],
        "support": 1,
        "exemplar_ids": ["exemplar-1"],
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def _candidate(record_id: str, tokens: int) -> build_sft_arms.Candidate:
    return build_sft_arms.Candidate(
        row={"record_id": record_id},
        record_id=record_id,
        source_key=f"project:{record_id}.cc",
        diagnostic="err_test",
        rendered_tokens=tokens,
        completion_tokens=max(1, tokens // 3),
        localized_input_hash=f"input-{record_id}",
        paired_source_hash=f"pair-{record_id}",
    )


def test_load_injector_map_is_semantics_preserving_and_detects_conflicts(
    tmp_path,
) -> None:
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    _write_jsonl(first, [_recipe()])
    _write_jsonl(second, [_recipe()])

    mapping, report = build_sft_arms.load_injector_map([first, second])

    expected = FuzzLangInjector.from_recipe_dict(_recipe())
    assert mapping["recipe-test"].injector_id == expected.injector_id
    assert report["recipe_rows"] == 2
    assert report["unique_recipe_ids"] == 1
    assert report["unique_injector_ids"] == 1

    conflicting = _recipe()
    conflicting["new_text"] = "other"
    conflicting["replacement_parts"] = [["literal", "other"]]
    _write_jsonl(second, [conflicting])
    with pytest.raises(ValueError, match="conflicting Injector identities"):
        build_sft_arms.load_injector_map([first, second])


def test_build_matched_arms_excludes_eval_leakage_and_backfills_injector_ids(
    tmp_path,
) -> None:
    paths = {}
    for method in ("mechanical", "direct_edit", "fuzzlang"):
        path = tmp_path / f"{method}.jsonl"
        _write_jsonl(path, [
            _row(f"{method}-a", f"project:{method}-a.cc", method=method),
            _row(f"{method}-b", f"project:{method}-b.cc", method=method),
            _row(f"{method}-leak", "project:eval.cc", method=method),
        ])
        paths[method] = [path]
    recipes = tmp_path / "recipes.jsonl"
    _write_jsonl(recipes, [_recipe()])
    eval_path = tmp_path / "eval.jsonl"
    _write_jsonl(
        eval_path,
        [_row("eval-1", "project:eval.cc", method="direct_edit")],
    )

    manifest = build_sft_arms.build_matched_arms(
        arm_paths=paths,
        eval_paths=[eval_path],
        recipe_paths=[recipes],
        tokenizer=FakeTokenizer(),
        tokenizer_name="fake-gemma",
        model_revision="revision-1",
        out_dir=tmp_path / "out",
        seed=42,
        budget_tokens=470,
        max_seq_len=4096,
        max_relative_token_gap=0.05,
    )

    assert manifest["token_budget"]["max_selected_tokens"] >= (
        manifest["token_budget"]["min_selected_tokens"]
    )
    assert manifest["token_budget"]["relative_gap"] <= 0.05
    assert manifest["cross_arm_selected_overlap"] == {
        "record_ids": 0,
        "source_keys": 0,
        "localized_input_hashes": 0,
        "paired_source_hashes": 0,
    }
    for method in paths:
        arm = manifest["arms"][method]
        assert arm["exclusions"]["eval_source_key"] == 1
        assert arm["selected_records"] >= 1
        output_rows = [
            json.loads(line)
            for line in Path(arm["output"]["path"]).read_text().splitlines()
        ]
        assert all(row["split"] == "train" for row in output_rows)
        assert all(
            row["provenance"]["detail"]["sft_arm"] == method
            for row in output_rows
        )

    fuzzlang_rows = [
        json.loads(line)
        for line in Path(
            manifest["arms"]["fuzzlang"]["output"]["path"]
        ).read_text().splitlines()
    ]
    expected = FuzzLangInjector.from_recipe_dict(_recipe())
    assert {
        row["provenance"]["detail"]["injector_id"]
        for row in fuzzlang_rows
    } == {expected.injector_id}
    assert all(
        row["provenance"]["detail"]["strategy"] == "learned_recipe_replay"
        for row in fuzzlang_rows
    )
    assert all(
        row["provenance"]["detail"]["injector_mapping"]
        == "semantics_preserving_recipe_adapter"
        for row in fuzzlang_rows
    )


def test_build_matched_arms_rejects_wrong_method_provenance(tmp_path) -> None:
    bad = _row("bad", "project:bad.cc", method="mechanical")
    bad["provenance"]["origin"] = "llm"
    path = tmp_path / "bad.jsonl"
    _write_jsonl(path, [bad])

    with pytest.raises(ValueError, match="Mechanical arm requires"):
        build_sft_arms.prepare_candidates(
            "mechanical",
            [path],
            tokenizer=FakeTokenizer(),
            eval_guard=build_sft_arms.EvalGuard.empty(),
            injector_by_recipe={},
            max_seq_len=4096,
        )


def test_count_and_token_matching_finds_largest_common_cardinality() -> None:
    arms = {
        "mechanical": [
            _candidate(f"m{i}", value)
            for i, value in enumerate((10, 20, 30, 40))
        ],
        "direct_edit": [
            _candidate(f"d{i}", value)
            for i, value in enumerate((15, 20, 25, 45))
        ],
        "fuzzlang": [
            _candidate(f"f{i}", value)
            for i, value in enumerate((20, 20, 25, 45))
        ],
    }

    count, budget = build_sft_arms.largest_common_count_budget(arms)
    selected = {
        arm: build_sft_arms.select_count_to_budget(
            candidates, count=count, budget=budget, seed=42, arm=arm
        )
        for arm, candidates in arms.items()
    }

    assert count == 3
    assert budget == 90
    assert {arm: len(rows) for arm, rows in selected.items()} == {
        arm: 3 for arm in arms
    }
    assert {
        arm: sum(row.rendered_tokens for row in rows)
        for arm, rows in selected.items()
    } == {arm: 90 for arm in arms}
