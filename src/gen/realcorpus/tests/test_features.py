from __future__ import annotations

from gen.realcorpus.features import fragment_features, target_features


def test_fragment_features_detects_constructs():
    f = fragment_features("template <class T> T f(T* p) { return p->g(); }")
    assert "template" in f
    assert "pointer" in f
    assert "member" in f       # -> access


def test_fragment_features_detects_call_and_class():
    f = fragment_features("struct S { int x; }; int main(){ return foo(1); }")
    assert "call" in f
    assert "class" in f


def test_target_features_maps_diagnostic_name():
    assert "call" in target_features("err_ovl_no_viable_function_in_call", "no matching function")
    assert "template" in target_features("err_template_arg_list", "template argument")
    assert "member" in target_features("err_no_member", "no member named 'x'")


def test_target_features_empty_for_generic_name():
    # A syntactic diagnostic maps to no structural feature (matches any fragment).
    assert target_features("err_expected_semi_declaration", "expected ';'") == frozenset()
