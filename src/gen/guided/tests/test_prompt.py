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
