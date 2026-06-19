"""Determinism + correctness tests for types.py — the shared vocabulary."""
from __future__ import annotations

from experiments.types import DiagInfo


def _make(**overrides) -> DiagInfo:
    defaults = dict(
        diag_id=123, diag_name="err_expected_semi", diag_msg="expected ';'",
        file="/tmp/a.c", line=3, col=10, start_byte=42, end_byte=50,
        span_snippet="int x = 1",
    )
    defaults.update(overrides)
    return DiagInfo(**defaults)


def test_span_hash_deterministic():
    d = _make()
    assert d.span_hash() == d.span_hash()


def test_span_hash_differs_on_diag_id():
    assert _make(diag_id=1).span_hash() != _make(diag_id=2).span_hash()


def test_span_hash_differs_on_byte_range():
    assert _make(start_byte=0).span_hash() != _make(start_byte=1).span_hash()
    assert _make(end_byte=50).span_hash() != _make(end_byte=51).span_hash()


def test_span_hash_whitespace_normalized():
    # "int  x = 1" vs "int x = 1" should hash equally after whitespace normalization.
    a = _make(span_snippet="int  x = 1")
    b = _make(span_snippet="int x = 1")
    assert a.span_hash() == b.span_hash()


def test_span_hash_differs_on_content():
    a = _make(span_snippet="int x = 1")
    b = _make(span_snippet="int y = 1")
    assert a.span_hash() != b.span_hash()


def test_span_hash_handles_none_diag_id():
    # Stock Clang may leave diag_id=None; hash must still be deterministic.
    d = _make(diag_id=None)
    assert d.span_hash() == d.span_hash()
    # And must differ from a diag_id=1 version.
    assert d.span_hash() != _make(diag_id=1).span_hash()
