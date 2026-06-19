"""Tests for the diagnostic catalog (coverage denominator).

Parses Clang's TableGen `.td` diagnostic definitions into a registry of
diagnostics, the authoritative denominator for coverage.
"""
import os

import pytest

from foundation.diagnostics.catalog import (
    DEFAULT_BASIC_DIR,
    DiagEntry,
    load_catalog,
    parse_td_text,
)

FIXTURE = r'''
let Component = "Ignored" in {
def err_simple : Error<"simple error %0">;
def err_multiline : Error<
  "line one "
  "line two">;
def warn_promoted : Warning<"promoted">, InGroup<SomeGroup>, DefaultError;
def warn_plain : Warning<"plain warning">, InGroup<SomeGroup>;
def ext_thing : Extension<"an extension">;
def note_thing : Note<"a note">;
def subst : TextSubstitution<"not a diagnostic">;
}
// def err_commented : Error<"nope">;
'''


def _by_name(text, **kw):
    return {e.name: e for e in parse_td_text(text, **kw)}


def test_parses_simple_error():
    e = _by_name(FIXTURE, component="Test")["err_simple"]
    assert isinstance(e, DiagEntry)
    assert e.severity == "Error"
    assert e.message == "simple error %0"
    assert e.component == "Test"
    assert e.is_error


def test_multiline_message_is_concatenated():
    e = _by_name(FIXTURE, component="Test")["err_multiline"]
    assert e.message == "line one line two"


def test_default_error_promotes_warning_to_error():
    entries = _by_name(FIXTURE, component="Test")
    wp = entries["warn_promoted"]
    assert wp.severity == "Warning"
    assert wp.in_group == "SomeGroup"
    assert wp.is_error  # promoted via DefaultError
    assert not entries["warn_plain"].is_error


def test_non_diagnostic_and_commented_defs_skipped():
    names = set(_by_name(FIXTURE, component="Test"))
    assert "subst" not in names          # TextSubstitution is not a diagnostic
    assert "err_commented" not in names  # lives inside a // comment


def test_extension_and_note_are_not_errors():
    entries = _by_name(FIXTURE, component="Test")
    assert entries["ext_thing"].severity == "Extension"
    assert not entries["ext_thing"].is_error
    assert entries["note_thing"].severity == "Note"
    assert not entries["note_thing"].is_error


@pytest.mark.skipif(
    not os.path.isdir(DEFAULT_BASIC_DIR),
    reason="LLVM submodule not checked out",
)
def test_real_catalog_denominator():
    cat = load_catalog()
    names = {e.name for e in cat.errors()}
    # The denominator should be substantial (thousands of error diagnostics).
    assert len(names) > 1500
    # Known stable diagnostics present in llvmorg-22.1.8.
    assert "err_typecheck_invalid_operands" in names
    assert "err_expected_semi_declaration" in names
    # TextSubstitution names must never leak into the catalog.
    assert "subst_format_overflow" not in {e.name for e in cat.entries}
    # Component is derived from the file name.
    assert cat.by_name["err_typecheck_invalid_operands"].component == "Sema"
