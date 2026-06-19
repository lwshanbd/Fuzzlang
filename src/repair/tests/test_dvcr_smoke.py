"""P002 end-to-end smoke test for DVCR via MockVerifier + StubSemicolonPolicy."""
from __future__ import annotations

from repair.agent.policy_base import PolicyContext
from repair.agent.policy_stub import NoOpPolicy, StubSemicolonPolicy
from repair.loop.search import run_dvcr
from repair.loop.terminal import TerminalReason
from foundation.types import DiagInfo, VerifierResult
from foundation.verifier.mock import MockVerifier, ok_result


BUGGY = "int main() {\n    int x = 1\n    return 0;\n}\n"
FIXED = "int main() {\n    int x = 1;\n    return 0;\n}\n"


def _make_verifier() -> MockVerifier:
    """Returns 'expected ;' on line 2 unless line 2 ends with ';' — then OK."""

    def policy(src: str, cmd: list[str], logical_path: str) -> VerifierResult:
        lines = src.splitlines()
        if len(lines) < 2:
            return VerifierResult(ok=False, diag=None, raw_stderr="__corrupt__")
        line2 = lines[1].rstrip()
        if line2.endswith(";"):
            return ok_result("ok\n")
        return VerifierResult(
            ok=False,
            diag=DiagInfo(
                diag_id=1001, diag_name="err_expected_semi",
                diag_msg="expected ';'",
                file=logical_path, line=2, col=len(line2) + 1,
                start_byte=0, end_byte=len(line2.encode("utf-8")),
                span_snippet=line2,
            ),
            raw_stderr=f"{logical_path}:2:{len(line2)+1}: error: expected ';'\nDiagID: 1001\n",
        )

    return MockVerifier(policy)


def test_smoke_semicolon_fix_succeeds_in_one_turn():
    v = _make_verifier()
    ctx = PolicyContext(signal_mode="full", k_proposals=4)
    result = run_dvcr(
        BUGGY, ["clang", "-c", "__SRC__"],
        v, StubSemicolonPolicy(), ctx, T=5, K=4,
        logical_path="/proj/smoke.c",
    )
    assert result.ok
    assert result.reason == TerminalReason.SUCCESS
    assert result.final_src.splitlines()[1].rstrip().endswith(";")
    assert result.turns_used == 1
    # Verifier was called: once initial + once for the proposed edit.
    assert result.verifier_calls == 2
    assert result.output_tokens_used == 0


def test_smoke_no_op_policy_returns_no_proposals():
    """Policy that never proposes should terminate with NO_PROPOSALS on turn 0."""
    v = _make_verifier()
    ctx = PolicyContext(signal_mode="full", k_proposals=4)
    result = run_dvcr(
        BUGGY, ["clang", "-c", "__SRC__"],
        v, NoOpPolicy(), ctx, T=3, K=4,
        logical_path="/proj/smoke.c",
    )
    assert not result.ok
    assert result.reason == TerminalReason.NO_PROPOSALS
    # Only the initial verifier call before agent tries.
    assert result.verifier_calls == 1


def test_smoke_initial_clean_source_is_trivial_success():
    v = _make_verifier()
    ctx = PolicyContext(signal_mode="full", k_proposals=4)
    result = run_dvcr(
        FIXED, ["clang", "-c", "__SRC__"],
        v, StubSemicolonPolicy(), ctx, T=5, K=4,
        logical_path="/proj/smoke.c",
    )
    assert result.ok
    assert result.turns_used == 0
    assert result.verifier_calls == 1


def test_smoke_signal_mode_no_struct_also_works_with_stub():
    """The stub reads only `observation['src']` and `observation['line']`, both
    present in every signal mode — so SIGNAL_NO_STRUCT must still succeed."""
    v = _make_verifier()
    ctx = PolicyContext(signal_mode="no_structure", k_proposals=4)
    result = run_dvcr(
        BUGGY, ["clang", "-c", "__SRC__"],
        v, StubSemicolonPolicy(), ctx, T=5, K=4,
        logical_path="/proj/smoke.c",
    )
    assert result.ok
