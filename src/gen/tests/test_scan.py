"""Unit tests for the code-aware character scanner.

Mutations must only touch *code* characters, never punctuation that happens to
sit inside a comment or a string/char literal — mutating those rarely breaks
compilation and just adds noise the verifier has to filter out.
"""
from __future__ import annotations

from gen.mutate._scan import iter_code_chars, code_mask


def _code_indices(src: str, ch: str) -> list[int]:
    return [i for i, c in iter_code_chars(src) if c == ch]


def test_plain_code_yields_every_char():
    src = "int x = 1;"
    assert "".join(c for _, c in iter_code_chars(src)) == src


def test_semicolon_inside_string_literal_is_not_code():
    src = 'const char* s = ";";'
    # Two ';' in the text; only the final statement terminator is code.
    semis = _code_indices(src, ";")
    assert semis == [len(src) - 1]


def test_char_literal_contents_are_skipped():
    src = "char c = ';';"
    semis = _code_indices(src, ";")
    assert semis == [len(src) - 1]


def test_line_comment_is_skipped():
    src = "int x = 1; // ; ; not code\nint y = 2;"
    semis = _code_indices(src, ";")
    assert semis == [9, len(src) - 1]


def test_block_comment_is_skipped():
    src = "int x = 1; /* ; ; */ int y = 2;"
    semis = _code_indices(src, ";")
    assert semis == [9, len(src) - 1]


def test_escaped_quote_does_not_end_string():
    src = r'const char* s = "a\";b"; int y;'
    # The ';' inside the (escaped) string must be skipped; only two real ';'.
    semis = _code_indices(src, ";")
    assert len(semis) == 2
    assert src[semis[0]] == ";" and src[semis[1]] == ";"


def test_code_mask_matches_iter():
    src = 'int x; char* s = ";";'
    mask = code_mask(src)
    assert len(mask) == len(src)
    assert [i for i, c in iter_code_chars(src)] == [i for i, m in enumerate(mask) if m]
