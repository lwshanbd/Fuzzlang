"""The mutation registry: list/select mutations by name."""
from __future__ import annotations

import pytest

import gen.mutate as M


EXPECTED_TEXT = {
    "delete_semicolon",
    "delete_bracket",
    "replace_colon_with_semicolon",
    "delete_comma",
}


def test_text_mutations_are_registered():
    names = {m.name for m in M.text_mutations()}
    assert EXPECTED_TEXT <= names


def test_get_returns_the_named_mutation():
    m = M.get("delete_semicolon")
    assert m.name == "delete_semicolon"
    assert m.mutate("int x = 1;")  # behaves like the concrete mutation


def test_get_unknown_raises_keyerror():
    with pytest.raises(KeyError):
        M.get("no_such_mutation")


def test_text_mutations_need_no_libclang():
    assert all(not m.requires_libclang for m in M.text_mutations())


def test_all_mutations_is_sorted_and_supersets_text():
    names = [m.name for m in M.all_mutations()]
    assert names == sorted(names)
    assert EXPECTED_TEXT <= set(names)
