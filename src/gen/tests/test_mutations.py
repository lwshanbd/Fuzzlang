"""Unit tests for the text/token-level mutations (no compiler involved).

Each mutation is a pure transform: correct source in, a list of Mutant
candidates out. We assert on the produced source text directly.
"""
from __future__ import annotations

from gen.mutate import Mutant
from gen.mutate.delete_semicolon import DeleteSemicolon
from gen.mutate.delete_bracket import DeleteBracket
from gen.mutate.replace_colon_semicolon import ReplaceColonWithSemicolon
from gen.mutate.delete_comma import DeleteComma


def _sources(mutants):
    return [m.src for m in mutants]


# ---- DeleteSemicolon ---------------------------------------------------------

def test_delete_semicolon_drops_the_terminator():
    muts = DeleteSemicolon().mutate("int x = 1;")
    assert "int x = 1" in _sources(muts)


def test_delete_semicolon_one_mutant_per_semicolon():
    muts = DeleteSemicolon().mutate("int x = 1; int y = 2;")
    assert _sources(muts) == ["int x = 1 int y = 2;", "int x = 1; int y = 2"]


def test_delete_semicolon_none_when_no_semicolon():
    assert DeleteSemicolon().mutate("int x = 1") == []


def test_delete_semicolon_ignores_semicolon_in_string():
    muts = DeleteSemicolon().mutate('const char* s = ";";')
    # Only the real terminator is a candidate, not the one inside the literal.
    assert _sources(muts) == ['const char* s = ";"']


def test_mutant_carries_description_and_diag_hint():
    m = DeleteSemicolon().mutate("int x = 1;")[0]
    assert isinstance(m, Mutant)
    assert m.description
    assert m.expected_diag is not None and "semi" in m.expected_diag


# ---- DeleteBracket -----------------------------------------------------------

def test_delete_bracket_removes_each_half_of_a_pair():
    srcs = _sources(DeleteBracket().mutate("int main() {}"))
    # Each mutant drops exactly one half of a matched pair, unbalancing the source.
    # The '(' ')' pair yields two mutants; the '{' '}' pair yields two.
    assert "int main) {}" in srcs         # '(' deleted
    assert "int main( {}" in srcs         # ')' deleted
    assert "int main() }" in srcs         # '{' deleted
    assert "int main() {" in srcs         # '}' deleted


def test_delete_bracket_ignores_unmatched_and_literal_brackets():
    # Bracket inside a string is not structural; nothing to pair, no mutants.
    srcs = _sources(DeleteBracket().mutate('const char* s = "(";'))
    assert srcs == []


# ---- ReplaceColonWithSemicolon ----------------------------------------------

def test_replace_colon_with_semicolon():
    srcs = _sources(ReplaceColonWithSemicolon().mutate("int a = b ? c : d;"))
    assert "int a = b ? c ; d;" in srcs


def test_replace_colon_skips_scope_resolution():
    # '::' must not be touched (would be a different, noisier mutation).
    assert ReplaceColonWithSemicolon().mutate("std::cout << x;") == []


# ---- DeleteComma -------------------------------------------------------------

def test_delete_comma():
    srcs = _sources(DeleteComma().mutate("int a, b;"))
    assert "int a b;" in srcs


def test_delete_comma_none_when_no_comma():
    assert DeleteComma().mutate("int a;") == []
