from __future__ import annotations

from foundation.record import Origin, Split
from foundation.types import DiagInfo, VerifierResult
from foundation.verifier.mock import MockVerifier, ok_result
from gen.realcorpus.collect import collect_real_record, count_errors
from gen.realcorpus.corpus import Fragment
from gen.realcorpus.targets import Target


def _frag():
    return Fragment(rel_path="clang/lib/A.cpp", tu_src="int f(){ return 0; }\n",
                    span=(0, 19), features=frozenset(), compile_cmd=["__CLANG__", "__SRC__"])


def _target(name="err_expected_semi"):
    return Target(name=name, message="expected ';'", features=frozenset(),
                  exemplar=None, covered=True)


def test_count_errors_counts_error_lines():
    assert count_errors("a.c:1:1: error: x\na.c:2:1: error: y\n") == 2


def test_collect_emits_record_with_cascade_and_target_match():
    stderr = "a.cpp:1:9: error: expected ';'\nDiagID: 1\na.cpp:1:9: error: cascade\n"
    diag = DiagInfo(diag_id=1, diag_name="err_expected_semi", diag_msg="expected ';'",
                    file="clang/lib/A.cpp", line=1, col=9, start_byte=0, end_byte=1,
                    span_snippet="x")

    def policy(src, cmd, logical_path):
        return VerifierResult(ok=False, diag=diag, raw_stderr=stderr)

    rec = collect_real_record(_frag(), "int f(){ return 0 }\n", _target(),
                              MockVerifier(policy), split=Split.EVAL)
    assert rec is not None
    assert rec.provenance.origin == Origin.GUIDED
    assert rec.provenance.detail["cascade_size"] == 2
    assert rec.provenance.detail["primary_matches_target"] is True
    assert rec.provenance.detail["target_diag"] == "err_expected_semi"
    assert rec.corrected_src == "int f(){ return 0; }\n"


def test_collect_returns_none_when_mutant_still_compiles():
    rec = collect_real_record(_frag(), "int f(){ return 0; }\n", _target(),
                              MockVerifier(lambda s, c, l: ok_result()))
    assert rec is None
