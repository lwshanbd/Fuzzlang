from __future__ import annotations

from gen.fuzzlang_dsl.injector import FuzzLangInjector
from gen.fuzzlang_dsl.merge_injectors import merge_injectors


def _injector(replacement: str) -> FuzzLangInjector:
    return FuzzLangInjector(target_diag="err_target", target_diag_id=None, language="c++", operation="replace", old_patterns=("x",), new_text=replacement, left_context=(), right_context=(), portable=True, replacement_parts=(("literal", replacement),))


def test_merge_injectors_keeps_first_unique_identity(tmp_path):
    a, b = _injector("a"), _injector("b")
    one, two = tmp_path / "one.jsonl", tmp_path / "two.jsonl"
    one.write_text(a.to_json() + "\n")
    two.write_text(a.to_json() + "\n" + b.to_json() + "\n")
    assert merge_injectors([one, two]) == [a, b]
