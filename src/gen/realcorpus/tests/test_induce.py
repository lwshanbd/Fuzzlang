from __future__ import annotations

from foundation.types import DiagInfo, VerifierResult
from foundation.verifier.mock import MockVerifier
from gen.realcorpus.corpus import Fragment
from gen.realcorpus.induce import induce_target
from gen.realcorpus.targets import Target


def _frag():
    return Fragment(rel_path="clang/lib/A.cpp", tu_src="int f(){ return 1; }\n",
                    span=(0, 20), features=frozenset(), compile_cmd=["__CLANG__", "__SRC__"])


def _target(name):
    return Target(name=name, message="m", features=frozenset(), exemplar=None, covered=False)


def _diag(name):
    return DiagInfo(diag_id=1, diag_name=name, diag_msg="m", file="f", line=1, col=1,
                    start_byte=0, end_byte=1, span_snippet="x")


def _edit_reply(m, t):
    return "<<<OLD\nreturn 1;\n===\nreturn 1\n>>>"


def test_induce_returns_exact_match():
    v = MockVerifier(lambda s, c, l: VerifierResult(ok=False, diag=_diag("err_target"),
                                                    raw_stderr="e"))
    out = induce_target(_target("err_target"), _frag(), _edit_reply, v, max_attempts=2)
    assert out is not None
    erroneous, res = out
    assert erroneous == "int f(){ return 1 }\n"
    assert res.diag.diag_name == "err_target"


def test_induce_returns_none_when_never_matches():
    calls = {"n": 0}

    def chat(m, t):
        calls["n"] += 1
        return "<<<OLD\nreturn 1;\n===\nreturn 1\n>>>"

    v = MockVerifier(lambda s, c, l: VerifierResult(ok=False, diag=_diag("err_other"),
                                                    raw_stderr="e"))
    out = induce_target(_target("err_target"), _frag(), chat, v, max_attempts=3)
    assert out is None                 # near-miss is NOT kept
    assert calls["n"] >= 2             # it retried on mismatch


def test_induce_gives_up_on_not_applicable():
    v = MockVerifier(lambda s, c, l: VerifierResult(ok=True, diag=None, raw_stderr=""))
    out = induce_target(_target("err_target"), _frag(),
                        lambda m, t: "NOT_APPLICABLE", v, max_attempts=3)
    assert out is None


def test_induce_reports_attempt_outcomes_and_near_misses():
    replies = iter([
        "<<<OLD\nreturn 1;\n===\nreturn 1\n>>>",
        "<<<OLD\nreturn 1;\n===\nreturn 1\n>>>",
    ])
    results = iter([
        VerifierResult(ok=False, diag=_diag("err_other"), raw_stderr="other"),
        VerifierResult(ok=False, diag=_diag("err_target"), raw_stderr="target"),
    ])
    events = []
    misses = []
    out = induce_target(
        _target("err_target"), _frag(), lambda m, t: next(replies),
        MockVerifier(lambda s, c, l: next(results)), max_attempts=2,
        on_attempt=events.append,
        on_near_miss=lambda target, frag, mutant, res: misses.append(
            res.diag.diag_name),
    )
    assert out is not None
    assert [e["status"] for e in events] == ["wrong_diagnostic", "exact_match"]
    assert events[0]["observed_diag"] == "err_other"
    assert misses == ["err_other"]


def test_induce_reports_not_applicable():
    events = []
    out = induce_target(
        _target("err_target"), _frag(), lambda m, t: "NOT_APPLICABLE",
        MockVerifier(lambda s, c, l: None), on_attempt=events.append,
    )
    assert out is None
    assert events[0]["status"] == "not_applicable"
