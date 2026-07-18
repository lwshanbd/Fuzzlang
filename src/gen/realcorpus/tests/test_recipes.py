from __future__ import annotations

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


def test_extract_and_apply_insertion_recipe_abstracts_identifiers():
    rec = _record("a", "int f() { return x; }", "int f() { return &x; }")
    recipe = extract_recipe(rec, context_tokens=2)

    assert recipe is not None
    assert recipe.diag_name == "err_typecheck_invalid_lvalue_addrof"
    assert recipe.operation == "insert"
    assert recipe.right_context[0] == "<ID>"
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
