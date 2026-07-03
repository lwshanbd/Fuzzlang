"""Tests for the guided-generation prompt builder."""
from gen.guided.prompt import build_pair_prompt


def test_prompt_includes_target_example_and_roles():
    msgs = build_pair_prompt(
        "err_undeclared_var_use", "use of undeclared identifier %0",
        "int f(){ return zzz; }")
    blob = "\n".join(m["content"] for m in msgs)
    assert "err_undeclared_var_use" in blob
    assert "int f(){ return zzz; }" in blob            # the example is shown
    assert any(m["role"] == "system" for m in msgs)
    assert any(m["role"] == "user" for m in msgs)
    assert "CORRECT" in blob and "BROKEN" in blob      # asks for both, labelled


def test_prompt_without_example_relies_on_name_and_message():
    msgs = build_pair_prompt(
        "err_typename_invalid_functionspec",
        "type name does not allow function specifier to be specified", "")
    blob = "\n".join(m["content"] for m in msgs)
    assert "err_typename_invalid_functionspec" in blob
    assert "type name does not allow function specifier" in blob
    assert "Example program" not in blob   # no empty example block shown
    assert "CORRECT" in blob and "BROKEN" in blob
