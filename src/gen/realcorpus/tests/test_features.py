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


def test_fragment_features_cover_declaration_and_modern_cpp_constructs():
    text = """
    #define FLAG 1
    namespace n { template<class... Ts> concept C = requires { sizeof...(Ts); }; }
    struct D : public B { [[nodiscard]] auto f() -> int; };
    """
    feats = fragment_features(text)
    assert {"preprocessor", "namespace", "template", "pack", "concept",
            "inheritance", "attribute", "auto"} <= feats


def test_fragment_features_cover_error_prone_runtime_constructs():
    text = "int a[4]; _Atomic int x; try { co_return; } catch (...) { __builtin_trap(); }"
    feats = fragment_features(text)
    assert {"array", "atomic", "exception", "coroutine", "builtin"} <= feats


def test_target_features_map_expanded_diagnostic_families():
    assert "attribute" in target_features("err_attribute_wrong_decl_type", "attribute")
    assert "concept" in target_features("err_requires_clause_on_non_templated_function",
                                        "requires clause")
    assert "preprocessor" in target_features("err_pp_expected_ident", "macro parameter")
    assert "inheritance" in target_features("err_base_must_be_class", "base class")
    assert "array" in target_features("err_array_size_non_int", "array size")
