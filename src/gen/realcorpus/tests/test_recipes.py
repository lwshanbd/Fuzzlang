from __future__ import annotations

import re

from foundation.record import Origin, Provenance, Record, Split
from foundation.types import DiagInfo
from gen.realcorpus.recipes import (
    apply_recipe,
    build_token_index,
    extract_recipe,
    extract_recipes,
    lex_tokens,
    minimal_edit,
)


def _record(
    record_id: str,
    corrected: str,
    erroneous: str,
    *,
    diag: str = "err_typecheck_invalid_lvalue_addrof",
) -> Record:
    info = DiagInfo(
        diag_id=1,
        diag_name=diag,
        diag_msg="m",
        file="llvm/lib/A.cpp",
        line=1,
        col=1,
        start_byte=0,
        end_byte=1,
        span_snippet="x",
    )
    return Record(
        record_id=record_id,
        erroneous_src=erroneous,
        corrected_src=corrected,
        diagnostics=(info,),
        provenance=Provenance(Origin.LLM, f"llvm:llvm/lib/{record_id}.cpp"),
        split=Split.EVAL,
    )


def test_minimal_edit_handles_insert_delete_and_replace():
    assert minimal_edit("return x;", "return &x;") == (7, "", "&")
    assert minimal_edit("return x;", "return x") == (8, ";", "")
    assert minimal_edit("class X", "union X") == (0, "class", "union")


def test_zero_context_extracts_no_lexical_anchor_tokens():
    rec = _record("a", "int f() { return x; }", "int f() { return &x; }")

    recipe = extract_recipe(rec, context_tokens=0)

    assert recipe is not None
    assert recipe.left_context == ()
    assert recipe.right_context == ()


def test_extract_and_apply_insertion_recipe_abstracts_identifiers():
    rec = _record("a", "int f() { return x; }", "int f() { return &x; }")
    recipe = extract_recipe(rec, context_tokens=2)

    assert recipe is not None
    assert recipe.diag_name == "err_typecheck_invalid_lvalue_addrof"
    assert recipe.operation == "insert"
    assert recipe.right_context[0].startswith("<ID")
    assert recipe.portable is True

    applications = apply_recipe("int g() { return value; }", recipe)
    assert any(app.src == "int g() { return &value; }" for app in applications)


def test_apply_recipe_does_not_match_comments_or_strings():
    rec = _record("a", "return x;", "return &x;")
    recipe = extract_recipe(rec, context_tokens=1)
    src = '// return value;\nconst char *s = "return value;";\n'
    assert apply_recipe(src, recipe) == []


def test_token_replacement_recipe_replays_on_new_identifier():
    rec = _record(
        "a", "class Widget {};", "union Widget {};", diag="err_base_clause_on_union"
    )
    recipe = extract_recipe(rec, context_tokens=1)
    applications = apply_recipe("class Other {};", recipe)
    assert [app.src for app in applications] == ["union Other {};"]


def test_inside_identifier_edit_is_not_portable():
    rec = _record("a", "int value;", "int valXue;", diag="err_x")
    recipe = extract_recipe(rec)
    assert recipe is not None
    assert recipe.portable is False
    assert apply_recipe("int other;", recipe) == []


def test_fixed_user_identifier_in_new_text_is_not_portable():
    rec = _record("a", "return x;", "return unknown_name + x;", diag="err_x")
    recipe = extract_recipe(rec)
    assert recipe is not None
    assert recipe.portable is False


def test_opt_in_fresh_identifiers_make_payload_local_names_portable():
    rec = _record(
        "a",
        "int f(){ return value; }",
        "int f(){ int temporary = 0; return temporary + value; }",
        diag="err_x",
    )

    recipe = extract_recipe(
        rec, context_tokens=2, allow_fresh_identifiers=True,
    )

    assert recipe is not None and recipe.portable
    fresh_parts = [part for part in recipe.replacement_parts if part[0] == "fresh"]
    assert fresh_parts == [("fresh", "FRESH0"), ("fresh", "FRESH0")]
    applications = apply_recipe(
        "int g(){ return item; }", recipe,
    )
    # The generated name is derived from the host file, so assert its shape and
    # its consistent reuse rather than a literal -- pinning the literal is what
    # let `fuzzlang_tmp` survive as a giveaway marker for weeks.
    assert len(applications) == 1
    generated = re.search(r"int (\w+) = 0", applications[0].src)
    assert generated, applications[0].src
    name = generated.group(1)
    assert "fuzzlang" not in name.lower()
    assert applications[0].src == f"int g()\u007b int {name} = 0; return {name} + item; \u007d"


def test_fresh_identifier_avoids_existing_source_names():
    rec = _record(
        "a",
        "int f(){ return value; }",
        "int f(){ int temporary = 0; return temporary + value; }",
        diag="err_x",
    )
    recipe = extract_recipe(rec, allow_fresh_identifiers=True)

    # Whatever name the recipe would pick, declaring it in the host file must
    # push the renderer to a different one.
    from gen.realcorpus.recipes import fresh_identifier_name

    collided = fresh_identifier_name(0, used_identifiers={"item"})
    applications = apply_recipe(
        f"int {collided}; int g()\u007b return item; \u007d", recipe,
    )

    assert applications
    generated = re.search(r"int (\w+) = 0", applications[0].src)
    assert generated and generated.group(1) != collided


def test_literal_payloads_remain_opt_in():
    rec = _record(
        "a",
        "int f(){ return value; }",
        'int f(){ static_assert(false, "injected"); return value; }',
        diag="err_x",
    )

    conservative = extract_recipe(rec, allow_fresh_identifiers=True)
    expanded = extract_recipe(
        rec,
        allow_fresh_identifiers=True,
        allow_literal_payloads=True,
    )

    assert conservative is not None and not conservative.portable
    assert expanded is not None and expanded.portable
    assert '"injected"' in apply_recipe(
        "int g(){ return item; }", expanded,
    )[0].src


def test_opt_in_token_normalization_expands_partial_numeric_edit():
    rec = _record(
        "a", "int f(){ return 1234; }", "int f(){ return 1294; }", diag="err_x"
    )

    conservative = extract_recipe(rec)
    normalized = extract_recipe(rec, normalize_token_edits=True)

    assert conservative is not None and not conservative.portable
    assert normalized is not None and normalized.portable
    assert normalized.old_patterns == ("<NUM>",)
    assert [app.src for app in apply_recipe(
        "int g(){ return 5678; }", normalized,
    )] == ["int g(){ return 1294; }"]


def test_opt_in_token_normalization_absorbs_intertoken_whitespace():
    rec = _record(
        "a",
        "template <typename T> bool f(T *p) { return true; }",
        "template <typename> bool f(typename *p) { return true; }",
        diag="err_x",
    )

    conservative = extract_recipe(rec)
    normalized = extract_recipe(rec, normalize_token_edits=True)

    assert conservative is not None and not conservative.portable
    assert normalized is not None and normalized.portable
    assert [app.src for app in apply_recipe(
        "template <typename U> bool g(U *q) { return false; }", normalized,
    )] == [
        "template <typename> bool g(typename *q) { return false; }",
    ]


def test_new_identifier_reused_from_context_becomes_metavariable():
    rec = _record(
        "a",
        "int f(){ return value + 0; }",
        "int f(){ return value + value; }",
        diag="err_x",
    )
    recipe = extract_recipe(rec, context_tokens=2)
    assert recipe is not None
    assert recipe.portable is True
    assert any(kind == "binding" for kind, _ in recipe.replacement_parts)
    assert [app.src for app in apply_recipe(
        "int g(){ return other + 0; }", recipe
    )] == ["int g(){ return other + other; }"]


def test_inserted_identifier_can_bind_to_left_context():
    rec = _record(
        "a", "int f(){ return value; }", "int f(){ return value(value); }",
        diag="err_x",
    )
    recipe = extract_recipe(rec, context_tokens=2)
    assert recipe is not None and recipe.portable
    assert [app.src for app in apply_recipe(
        "int g(){ return item; }", recipe
    )] == ["int g(){ return item(item); }"]


def test_inserted_identifier_spelling_can_be_preserved_as_literal_payload():
    rec = _record(
        "a",
        "int f(){ return 0; }",
        "int f(){ Missing value; return 0; }",
        diag="err_x",
    )

    recipe = extract_recipe(
        rec,
        context_tokens=2,
        allow_fresh_identifiers=True,
        preserve_inserted_identifier_spellings=True,
    )

    assert recipe is not None and recipe.portable
    assert ("literal", "Missing") in recipe.replacement_parts
    assert ("literal", "value") in recipe.replacement_parts
    assert [app.src for app in apply_recipe(
        "int g(){ return 0; }", recipe,
    )] == ["int g(){ Missing value; return 0; }"]


def test_recipe_json_round_trip_preserves_replacement_bindings():
    from gen.realcorpus.recipes import LearnedRecipe

    rec = _record(
        "a",
        "int f(){ return value + 0; }",
        "int f(){ return value + value; }",
        diag="err_x",
    )
    recipe = extract_recipe(rec, context_tokens=2)
    restored = LearnedRecipe.from_dict(recipe.to_dict())
    assert restored == recipe
    assert apply_recipe(
        "int g(){ return item + 0; }", restored
    )[0].src == "int g(){ return item + item; }"


def test_v1_recipe_json_without_template_keeps_literal_replacement():
    from gen.realcorpus.recipes import LearnedRecipe

    recipe = extract_recipe(
        _record("a", "return value;", "return &value;"), context_tokens=1
    )
    encoded = recipe.to_dict()
    encoded.pop("replacement_parts")
    restored = LearnedRecipe.from_dict(encoded)

    assert restored.replacement_parts == (("literal", "&"),)
    assert apply_recipe("return other;", restored)[0].src == "return &other;"


def test_repeated_identifier_metavariable_requires_same_target_name():
    recipe = extract_recipe(_record(
        "a", "return value + value;", "return value - value;", diag="err_x"
    ))

    assert apply_recipe("return item + item;", recipe)[0].src == "return item - item;"
    assert apply_recipe("return item + other;", recipe) == []


def test_large_spanning_edit_is_not_portable():
    corrected = "int f(){ return " + ("x + " * 100) + "0; }"
    erroneous = "int f(){ return y; }"
    recipe = extract_recipe(
        _record("a", corrected, erroneous, diag="err_x"),
        max_edit_chars=128,
    )
    assert recipe is not None
    assert recipe.portable is False


def test_extract_recipes_aggregates_same_diagnostic_pattern_support():
    records = [
        _record("a", "int f(){ return x; }", "int f(){ return &x; }"),
        _record("b", "int g(){ return y; }", "int g(){ return &y; }"),
    ]
    recipes = extract_recipes(records, context_tokens=2)
    assert len(recipes) == 1
    assert recipes[0].support == 2
    assert recipes[0].exemplar_ids == ("a", "b")


def test_recipe_identity_is_diagnostic_specific():
    records = [
        _record("a", "return x;", "return &x;", diag="err_a"),
        _record("b", "return y;", "return &y;", diag="err_b"),
    ]
    recipes = extract_recipes(records, context_tokens=1)
    assert len(recipes) == 2
    assert {recipe.diag_name for recipe in recipes} == {"err_a", "err_b"}


def test_indexed_replay_matches_unindexed_replay():
    rec = _record("a", "return x;", "return &x;")
    recipe = extract_recipe(rec, context_tokens=1)
    src = "int f(){ return first; } int g(){ return second; }"
    tokens = lex_tokens(src)
    assert apply_recipe(
        src, recipe, tokens=tokens, token_index=build_token_index(tokens)
    ) == apply_recipe(src, recipe)


def test_generated_identifiers_do_not_announce_their_own_provenance():
    # Injected code named its placeholders `fuzzlang_tmp`, so 41-46% of
    # evaluation instances carried a literal marker on the broken side and never
    # on the fixed side. A model can find the error by searching for it, and the
    # fine-tuned one learned to. Generated names must be collision-free without
    # being recognisable.
    from gen.realcorpus.recipes import fresh_identifier_name

    name = fresh_identifier_name(0, used_identifiers={"item", "count"})
    assert "fuzzlang" not in name.lower()
    assert re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)


def test_generated_identifiers_avoid_collisions_with_the_host_file():
    from gen.realcorpus.recipes import fresh_identifier_name

    used = {"item"}
    first = fresh_identifier_name(0, used_identifiers=used)
    # Pretend the host file already contains it; the next attempt must move on.
    second = fresh_identifier_name(0, used_identifiers=used | {first})
    assert first != second


def test_generated_identifiers_differ_between_files_so_they_are_not_a_constant_tell():
    from gen.realcorpus.recipes import fresh_identifier_name

    a = fresh_identifier_name(0, used_identifiers={"alpha", "beta"})
    b = fresh_identifier_name(0, used_identifiers={"gamma", "delta"})
    assert a != b


def test_generated_identifiers_are_deterministic_for_the_same_file():
    from gen.realcorpus.recipes import fresh_identifier_name

    used = {"alpha", "beta"}
    assert fresh_identifier_name(0, used_identifiers=used) == fresh_identifier_name(
        0, used_identifiers=set(used)
    )
    assert fresh_identifier_name(0, used_identifiers=used) != fresh_identifier_name(
        1, used_identifiers=used
    )
