from __future__ import annotations

from gen.realcorpus.corpus import Fragment
from gen.realcorpus.ranking import rank_fragments
from gen.realcorpus.targets import Target


def _frag(feats, path="f", span=(0, 1)):
    return Fragment(rel_path=path, tu_src="x", span=span,
                    features=frozenset(feats), compile_cmd=["__CLANG__", "__SRC__"])


def test_rank_gates_to_feature_matching_fragments():
    target = Target(name="err_ovl", message="no matching function",
                    features=frozenset({"call"}), exemplar=None, covered=False)
    frags = [_frag(set()), _frag({"call"}), _frag({"template"})]
    ranked = rank_fragments(target, frags, k=3)
    assert [f.features for f in ranked] == [frozenset({"call"})]  # only the applicable one


def test_rank_returns_empty_when_no_fragment_matches():
    target = Target(name="x", message="y", features=frozenset({"lambda"}),
                    exemplar=None, covered=False)
    assert rank_fragments(target, [_frag({"call"})], k=3) == []


def test_rank_no_target_features_returns_first_k():
    target = Target(name="err_semi", message="expected ';'",
                    features=frozenset(), exemplar=None, covered=False)
    frags = [_frag({"a"}), _frag({"b"}), _frag({"c"})]
    assert len(rank_fragments(target, frags, k=2)) == 2


def test_rank_prefers_distinct_translation_units_before_reusing_one():
    target = Target(name="err_semi", message="expected ';'",
                    features=frozenset(), exemplar=None, covered=False)
    frags = [
        _frag({"call"}, path="a.cpp", span=(0, 1)),
        _frag({"call"}, path="a.cpp", span=(2, 3)),
        _frag({"call"}, path="b.cpp", span=(0, 1)),
    ]
    ranked = rank_fragments(target, frags, k=2)
    assert {f.rel_path for f in ranked} == {"a.cpp", "b.cpp"}


def test_rank_tie_break_varies_deterministically_by_target():
    frags = [_frag(set(), path=f"{x}.cpp") for x in "abcdef"]
    a = Target(name="err_a", message="m", features=frozenset(),
               exemplar=None, covered=False)
    b = Target(name="err_b", message="m", features=frozenset(),
               exemplar=None, covered=False)
    assert rank_fragments(a, frags, k=3) == rank_fragments(a, frags, k=3)
    assert rank_fragments(a, frags, k=3) != rank_fragments(b, frags, k=3)
