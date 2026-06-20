"""Tests for the diagnostic matcher (stderr-message -> diagnostic name).

Fallback path for stock Clang (no DiagID): convert each catalog diagnostic's
message template (with %0 / %select{} / %plural{} ...) to a regex and match a
rendered diagnostic message back to its name.
"""
import os

import pytest

from foundation.diagnostics.catalog import DEFAULT_BASIC_DIR, Catalog, DiagEntry, load_catalog
from foundation.diagnostics.matcher import DiagnosticMatcher, template_to_regex


def _cat():
    e = lambda n, m: DiagEntry(name=n, severity="Error", message=m, component="Sema")
    return Catalog([
        e("err_expected", "expected %0"),
        e("err_undeclared", "use of undeclared identifier %0"),
        e("err_cannot", "cannot %select{convert|assign to}0 it"),
        e("err_plural", "found %0 %plural{1:error|:errors}0"),
        e("err_any", "%0"),
    ])


def test_placeholder_match():
    m = DiagnosticMatcher(_cat())
    assert m.match("use of undeclared identifier 'foo'") == "err_undeclared"


def test_expected_match():
    m = DiagnosticMatcher(_cat())
    assert m.match("expected ';'") == "err_expected"


def test_select_alternatives_match():
    m = DiagnosticMatcher(_cat())
    assert m.match("cannot convert it") == "err_cannot"
    assert m.match("cannot assign to it") == "err_cannot"


def test_plural_alternatives_match():
    m = DiagnosticMatcher(_cat())
    assert m.match("found 2 errors") == "err_plural"


def test_degenerate_template_is_skipped():
    # "%0" -> ".*" would match everything; it must be dropped, not catch-all.
    m = DiagnosticMatcher(_cat())
    assert m.match("zzz totally unrelated qqq") is None


def test_unmatched_message_returns_none():
    m = DiagnosticMatcher(_cat())
    assert m.match("this is not any known diagnostic at all") is None


def test_template_to_regex_escapes_literals():
    # parentheses in the template must be literal, not regex groups.
    rx = template_to_regex("call to function (a.b)")
    import re
    assert re.fullmatch(rx, "call to function (a.b)")
    assert not re.fullmatch(rx, "call to function axb")


@pytest.mark.skipif(not os.path.isdir(DEFAULT_BASIC_DIR), reason="LLVM submodule not checked out")
def test_real_matcher_builds_and_matches():
    m = DiagnosticMatcher(load_catalog())
    assert len(m) > 1000
    assert m.match("use of undeclared identifier 'foo'") is not None
