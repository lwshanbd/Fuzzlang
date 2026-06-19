"""P001 unit tests — verifier contract via MockVerifier."""
from __future__ import annotations

from experiments.types import DiagInfo, VerifierResult
from experiments.verifier.mock import MockVerifier, ok_result


def _err_result(msg: str = "expected ';'", diag_id: int | None = 123,
                line: int = 1, snippet: str = "int x = 1",
                logical_path: str = "/proj/a.c") -> VerifierResult:
    return VerifierResult(
        ok=False,
        diag=DiagInfo(
            diag_id=diag_id,
            diag_name="err_expected_semi",
            diag_msg=msg,
            file=logical_path,
            line=line,
            col=10,
            start_byte=0,
            end_byte=len(snippet.encode("utf-8")),
            span_snippet=snippet,
        ),
        raw_stderr=f"{logical_path}:{line}:10: error: {msg}\nDiagID: {diag_id}\n",
    )


def test_mock_records_calls_with_logical_path():
    first = True

    def policy(src, cmd, logical_path):
        nonlocal first
        if first:
            first = False
            return _err_result(logical_path=logical_path)
        return ok_result()

    v = MockVerifier(policy)
    r1 = v.verify("src-v1", ["clang", "-c", "__SRC__"], logical_path="/proj/a.c")
    assert not r1.ok and r1.diag is not None and r1.diag.diag_id == 123
    assert r1.diag.file == "/proj/a.c"   # logical path, not a tempfile.

    r2 = v.verify("src-v2", ["clang", "-c", "__SRC__"], logical_path="/proj/a.c")
    assert r2.ok

    assert len(v.call_log) == 2
    assert v.call_log[0][2] == "/proj/a.c"


def test_mock_supports_sequence_of_diagnostics():
    seq = iter([
        _err_result(msg="expected ';'", diag_id=101),
        _err_result(msg="use of undeclared identifier 'x'", diag_id=202),
        ok_result(),
    ])
    v = MockVerifier(lambda src, cmd, logical_path: next(seq))
    r1 = v.verify("s1", [], logical_path="/p/a.c")
    r2 = v.verify("s2", [], logical_path="/p/a.c")
    r3 = v.verify("s3", [], logical_path="/p/a.c")
    assert r1.diag.diag_id == 101
    assert r2.diag.diag_id == 202
    assert r3.ok


def test_span_hash_is_stable_across_calls_with_same_logical_path():
    """Regression: earlier bug made span_hash change because verifiers put the
    tempfile path into DiagInfo.file. With logical_path, repeated verifies of
    the same logical source give the same hash."""
    v = MockVerifier(lambda src, cmd, logical_path: _err_result(logical_path=logical_path))
    r1 = v.verify("src", ["clang"], logical_path="/proj/a.c")
    r2 = v.verify("src", ["clang"], logical_path="/proj/a.c")
    assert r1.diag.span_hash() == r2.diag.span_hash()
