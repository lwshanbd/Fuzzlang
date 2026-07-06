from __future__ import annotations

from gen.realcorpus.prompt import Edit, build_inject_prompt, parse_edit
from gen.realcorpus.targets import Target


def _target():
    return Target(name="err_no_member", message="no member named 'x'",
                  features=frozenset({"member"}), exemplar="s.x;", covered=True)


def test_build_prompt_includes_target_and_region_and_exemplar():
    msgs = build_inject_prompt(_target(), "int f(S s){ return s.y; }", "struct S{int y;};")
    blob = "\n".join(m["content"] for m in msgs)
    assert "err_no_member" in blob
    assert "s.y" in blob            # region text
    assert "s.x;" in blob           # exemplar
    assert any(m["role"] == "system" for m in msgs)


def test_parse_edit_reads_old_new_block():
    reply = "reasoning...\n<<<OLD\nreturn s.y;\n===\nreturn s.zzz;\n>>>"
    e = parse_edit(reply)
    assert e == Edit(old="return s.y;", new="return s.zzz;")


def test_parse_edit_handles_not_applicable_and_junk():
    assert parse_edit("NOT_APPLICABLE") is None
    assert parse_edit("no markers here") is None
