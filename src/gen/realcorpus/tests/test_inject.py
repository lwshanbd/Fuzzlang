from __future__ import annotations

from gen.realcorpus.corpus import Fragment
from gen.realcorpus.inject import apply_edit, inject_target
from gen.realcorpus.prompt import Edit
from gen.realcorpus.targets import Target


def test_apply_edit_replaces_unique_anchor():
    tu = "int f(){ return 1; }\n"
    assert apply_edit(tu, Edit(old="return 1;", new="return 1")) == "int f(){ return 1 }\n"


def test_apply_edit_rejects_absent_or_nonunique():
    assert apply_edit("a a a", Edit(old="a", new="b")) is None   # non-unique
    assert apply_edit("xyz", Edit(old="q", new="b")) is None     # absent


def test_inject_target_end_to_end_with_mock_chat():
    frag = Fragment(rel_path="f.cpp", tu_src="int f(){ return 1; }\n",
                    span=(0, 20), features=frozenset(), compile_cmd=["__CLANG__", "__SRC__"])
    target = Target(name="err_expected_semi", message="expected ';'",
                    features=frozenset(), exemplar=None, covered=False)

    def chat(messages, temperature):
        return "<<<OLD\nreturn 1;\n===\nreturn 1\n>>>"

    out = inject_target(target, frag, chat, retries=1)
    assert out == "int f(){ return 1 }\n"


def test_inject_target_gives_up_on_not_applicable():
    frag = Fragment(rel_path="f.cpp", tu_src="int f(){ return 1; }\n",
                    span=(0, 20), features=frozenset(), compile_cmd=["__CLANG__", "__SRC__"])
    target = Target(name="err_x", message="x", features=frozenset(),
                    exemplar=None, covered=False)
    out = inject_target(target, frag, lambda m, t: "NOT_APPLICABLE", retries=2)
    assert out is None
