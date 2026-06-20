"""Tests for mining example snippets per diagnostic from a corpus."""
from foundation.types import DiagInfo, VerifierResult
from foundation.verifier.mock import MockVerifier, ok_result
from gen.guided.examples import mine_examples


def _err(name):
    d = DiagInfo(diag_id=1, diag_name=name, diag_msg="m", file="f", line=1, col=1,
                 start_byte=0, end_byte=1, span_snippet="x")
    return VerifierResult(ok=False, diag=d, raw_stderr="error")


def test_groups_snippets_by_diagnostic():
    def policy(s, c, l):
        if s.startswith("A"):
            return _err("err_a")
        if s == "B":
            return _err("err_b")
        return ok_result()
    idx = mine_examples([("A1", "s1"), ("B", "s2"), ("A2", "s3")], MockVerifier(policy))
    assert idx == {"err_a": ["A1", "A2"], "err_b": ["B"]}


def test_skips_clean_and_unnamed():
    noname = VerifierResult(
        ok=False,
        diag=DiagInfo(diag_id=None, diag_name=None, diag_msg="m", file="f", line=1,
                      col=1, start_byte=0, end_byte=1, span_snippet="x"),
        raw_stderr="error")

    def policy(s, c, l):
        if s == "clean":
            return ok_result()
        if s == "noname":
            return noname
        return _err("err_x")
    idx = mine_examples([("clean", "1"), ("noname", "2"), ("bad", "3")], MockVerifier(policy))
    assert idx == {"err_x": ["bad"]}


def test_max_per_diag_caps_examples():
    idx = mine_examples([("x1", "a"), ("x2", "b"), ("x3", "c")],
                        MockVerifier(lambda s, c, l: _err("err_x")), max_per_diag=2)
    assert idx == {"err_x": ["x1", "x2"]}
