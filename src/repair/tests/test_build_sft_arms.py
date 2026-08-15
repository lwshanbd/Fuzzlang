import json
from pathlib import Path

import pytest

from gen.fuzzlang_dsl import FuzzLangInjector
from gen.realcorpus.recipes import LearnedRecipe
from repair import build_sft_arms
from repair.build_sft_arms import (
    Candidate, select_by_breadth, select_scaling_tiers,
)


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


def _library_replay_row(record_id: str, source_key: str, injector_id: str) -> dict:
    row = _row(record_id, source_key, method="fuzzlang")
    row["provenance"]["detail"] = {
        "strategy": "fuzzlang_library_replay",
        "injector_id": injector_id,
        "target_diag": "err_undeclared_var_use",
        "source_path": source_key.split(":", 1)[1],
    }
    return row


def test_library_replay_rows_are_accepted_via_their_immutable_injector_id(
    tmp_path,
) -> None:
    """E1 replays a released library, so a record names its Injector directly.

    That is stronger provenance than the recipe indirection: the Injector ID is
    a content hash of the artifact, so it cannot silently drift.
    """
    injector = FuzzLangInjector.from_recipe(LearnedRecipe(**_recipe()))
    row = _library_replay_row("rec-1", "llvm:a.cc", injector.injector_id)

    derived = build_sft_arms.validated_arm_row(
        row, method="fuzzlang", location="mem:1",
        injector_by_recipe={}, injector_by_id={injector.injector_id: injector},
    )

    assert derived["provenance"]["detail"]["sft_arm"] == "fuzzlang"
    assert derived["provenance"]["detail"]["injector_id"] == injector.injector_id
    assert derived["provenance"]["detail"]["injector_content_hash"] == (
        injector.content_hash
    )
    assert derived["split"] == "train"


def test_a_library_replay_row_naming_an_unknown_injector_is_rejected(tmp_path) -> None:
    row = _library_replay_row("rec-1", "llvm:a.cc", "fuzzlang-v2-not-in-library")

    with pytest.raises(ValueError, match="Injector"):
        build_sft_arms.validated_arm_row(
            row, method="fuzzlang", location="mem:1",
            injector_by_recipe={}, injector_by_id={},
        )


def test_recipe_paths_are_optional_when_a_pinned_library_is_supplied(tmp_path) -> None:
    """A released-library replay needs no recipe map; requiring one is noise."""
    parser_error = None
    try:
        build_sft_arms.require_injector_authority(recipes=[], library=["lib.jsonl"])
    except ValueError as error:  # pragma: no cover - asserted below
        parser_error = error
    assert parser_error is None

    with pytest.raises(ValueError, match="recipe"):
        build_sft_arms.require_injector_authority(recipes=[], library=[])


def test_overlength_records_are_excluded_explicitly_never_silently(tmp_path) -> None:
    """The plan forbids silent truncation or dropping of overlength examples.

    Raising is the safe default. When a corpus legitimately contains windows
    wider than the context budget, the caller must opt in and the count lands in
    the exclusion report, so no example disappears without a number attached.
    """
    assert build_sft_arms.overlength_disposition(
        rendered_tokens=5_000, max_seq_len=1_024, on_overlength="exclude",
    ) == "overlength"
    assert build_sft_arms.overlength_disposition(
        rendered_tokens=100, max_seq_len=1_024, on_overlength="exclude",
    ) is None
    with pytest.raises(ValueError, match="no implicit truncation"):
        build_sft_arms.overlength_disposition(
            rendered_tokens=5_000, max_seq_len=1_024, on_overlength="error",
        )


def test_manifest_records_the_overlength_policy_that_actually_ran(tmp_path) -> None:
    """A manifest that misreports the run is worse than no manifest.

    The overlength policy decides whether examples were dropped, so hardcoding
    it would claim `error` (nothing dropped) on a run that excluded examples.
    """
    import inspect

    source = inspect.getsource(build_sft_arms.build_matched_arms)
    assert '"overlong_policy": "error"' not in source
    assert '"overlong_policy": on_overlength' in source


def test_scaling_sizes_are_nested_so_the_curve_isolates_quantity():
    # A data-scaling curve only isolates *how much* data if the smaller arm is a
    # subset of the larger one. Otherwise a difference could come from which
    # records were drawn rather than from how many.
    candidates = [
        Candidate(
            record_id=f"r{n}", row={"record_id": f"r{n}"}, source_key=f"s{n}",
            diagnostic="err_a", rendered_tokens=100 + n, completion_tokens=10,
            localized_input_hash=f"h{n}", paired_source_hash=f"p{n}",
        )
        for n in range(20)
    ]

    tiers = select_scaling_tiers(candidates, sizes=[4, 8, 16], seed=42)

    assert [len(tiers[size]) for size in (4, 8, 16)] == [4, 8, 16]
    ids = {size: {c.record_id for c in tiers[size]} for size in tiers}
    assert ids[4] < ids[8] < ids[16]


def test_scaling_rejects_a_size_larger_than_the_pool():
    candidates = [
        Candidate(
            record_id=f"r{n}", row={"record_id": f"r{n}"}, source_key=f"s{n}",
            diagnostic="err_a", rendered_tokens=100, completion_tokens=10,
            localized_input_hash=f"h{n}", paired_source_hash=f"p{n}",
        )
        for n in range(5)
    ]
    with pytest.raises(ValueError):
        select_scaling_tiers(candidates, sizes=[4, 9], seed=42)


def test_scaling_order_is_deterministic_and_independent_of_input_order():
    def pool():
        return [
            Candidate(
                record_id=f"r{n}", row={"record_id": f"r{n}"}, source_key=f"s{n}",
                diagnostic="err_a", rendered_tokens=100 + (n % 7), completion_tokens=10,
                localized_input_hash=f"h{n}", paired_source_hash=f"p{n}",
            )
            for n in range(12)
        ]

    forward = select_scaling_tiers(pool(), sizes=[3, 6], seed=7)
    reverse = select_scaling_tiers(list(reversed(pool())), sizes=[3, 6], seed=7)

    assert [c.record_id for c in forward[3]] == [c.record_id for c in reverse[3]]
    assert [c.record_id for c in forward[6]] == [c.record_id for c in reverse[6]]


def _diag_pool():
    """20 records: 'err_common' holds 11, the rest hold 1 each."""
    pool = []
    for n in range(11):
        pool.append(Candidate(
            record_id=f"c{n}", row={"record_id": f"c{n}"}, source_key=f"s{n}",
            diagnostic="err_common", rendered_tokens=100, completion_tokens=10,
            localized_input_hash=f"h{n}", paired_source_hash=f"p{n}"))
    for n in range(9):
        pool.append(Candidate(
            record_id=f"r{n}", row={"record_id": f"r{n}"}, source_key=f"t{n}",
            diagnostic=f"err_{n}", rendered_tokens=100, completion_tokens=10,
            localized_input_hash=f"g{n}", paired_source_hash=f"q{n}"))
    return pool


def test_breadth_modes_hold_the_record_count_and_move_only_the_coverage():
    # The scaling curve grew volume and diagnostic coverage together. To tell
    # them apart we need two arms of the same size whose coverage differs.
    narrow = select_by_breadth(_diag_pool(), count=10, mode="narrow", seed=42)
    broad = select_by_breadth(_diag_pool(), count=10, mode="broad", seed=42)

    assert len(narrow) == len(broad) == 10
    narrow_diags = {c.diagnostic for c in narrow}
    broad_diags = {c.diagnostic for c in broad}
    # narrow fills from the most populous diagnostic first...
    assert narrow_diags == {"err_common"}
    # ...broad spreads one per diagnostic before taking a second from any.
    assert len(broad_diags) == 10


def test_broad_mode_spreads_evenly_while_every_diagnostic_still_has_records():
    # Round-robin can only stay balanced while records remain; once a
    # diagnostic is exhausted the rest must absorb the remainder. Check the
    # invariant on a pool where nothing runs out.
    from collections import Counter

    balanced = [
        Candidate(
            record_id=f"d{d}-{n}", row={"record_id": f"d{d}-{n}"},
            source_key=f"s{d}{n}", diagnostic=f"err_{d}",
            rendered_tokens=100, completion_tokens=10,
            localized_input_hash=f"h{d}{n}", paired_source_hash=f"p{d}{n}",
        )
        for d in range(5) for n in range(4)
    ]
    counts = Counter(
        c.diagnostic for c in select_by_breadth(
            balanced, count=12, mode="broad", seed=42)
    )

    assert len(counts) == 5
    assert max(counts.values()) - min(counts.values()) <= 1


def test_broad_mode_exhausts_small_diagnostics_before_repeating_a_large_one():
    # err_common holds 11 records, nine others hold 1 each. Asking for 12 must
    # take all nine singletons rather than 12 copies of the easy diagnostic.
    broad = select_by_breadth(_diag_pool(), count=12, mode="broad", seed=42)
    assert len({c.diagnostic for c in broad}) == 10


def test_breadth_selection_rejects_an_impossible_count():
    with pytest.raises(ValueError):
        select_by_breadth(_diag_pool(), count=99, mode="broad", seed=42)


def test_breadth_selection_is_deterministic():
    a = select_by_breadth(_diag_pool(), count=10, mode="broad", seed=7)
    b = select_by_breadth(list(reversed(_diag_pool())), count=10, mode="broad", seed=7)
    assert [c.record_id for c in a] == [c.record_id for c in b]
