from __future__ import annotations

from gen.realcorpus.corpus import Fragment
from gen.realcorpus.ranking import rank_fragments
from gen.realcorpus.targets import Target


def _frag(feats):
    return Fragment(rel_path="f", tu_src="x", span=(0, 1),
                    features=frozenset(feats), compile_cmd=["__CLANG__", "__SRC__"])


def test_rank_prefers_feature_overlap():
    target = Target(name="err_ovl", message="no matching function",
                    features=frozenset({"call"}), exemplar=None, covered=False)
    frags = [_frag(set()), _frag({"call"}), _frag({"template"})]
    ranked = rank_fragments(target, frags, k=2)
    assert ranked[0].features == frozenset({"call"})  # best overlap first
    assert len(ranked) == 2


def test_rank_no_target_features_returns_first_k():
    target = Target(name="err_semi", message="expected ';'",
                    features=frozenset(), exemplar=None, covered=False)
    frags = [_frag({"a"}), _frag({"b"}), _frag({"c"})]
    assert len(rank_fragments(target, frags, k=2)) == 2
