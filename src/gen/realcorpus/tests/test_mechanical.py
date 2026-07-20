from __future__ import annotations

from foundation.record import Origin, Provenance, Record, Split
from foundation.types import DiagInfo, VerifierResult
from foundation.verifier.mock import MockVerifier, ok_result
from gen.mutate.delete_semicolon import DeleteSemicolon
from gen.realcorpus.mechanical import (
    mutate_real_source,
    select_real_source_records,
)


CORRECT = "int f(){ int a = 0; int b = 1; return a + b; }"
CMD = ["__CLANG__", "-fsyntax-only", "__SRC__"]


def _diag(name: str = "err_expected_semi_declaration") -> DiagInfo:
    return DiagInfo(
        diag_id=1650,
        diag_name=name,
        diag_msg="expected ';'",
        file="ignored.cpp",
        line=1,
        col=10,
        start_byte=0,
        end_byte=1,
        span_snippet="x",
    )


def _parent(
    record_id: str,
    *,
    source: str = "llvm:llvm/lib/A.cpp",
    source_path: str = "llvm/lib/A.cpp",
    corrected: str = CORRECT,
    compile_cmd=CMD,
    language: str = "c++",
) -> Record:
    return Record(
        record_id=record_id,
        erroneous_src=corrected.replace("return", "return &", 1),
        corrected_src=corrected,
        diagnostics=(_diag("err_parent"),),
        provenance=Provenance(
            Origin.MUTATE,
            source,
            detail={
                "compile_cmd": compile_cmd,
                "source_path": source_path,
            },
        ),
        split=Split.EVAL,
        language=language,
    )


def _error_result(name: str = "err_expected_semi_declaration") -> VerifierResult:
    return VerifierResult(
        ok=False,
        diag=_diag(name),
        raw_stderr="llvm/lib/A.cpp:1:10: error: expected ';'\n",
    )


def test_source_selection_deduplicates_provenance_and_strictly_excludes_tests():
    selected = select_real_source_records([
        _parent("b"),
        _parent("a"),
        _parent(
            "test",
            source="llvm:clang/lib/Testing/Support.cpp",
            source_path="clang/lib/Testing/Support.cpp",
        ),
        _parent("bad-cmd", source="llvm:llvm/lib/Bad.cpp", compile_cmd=["clang"]),
    ])

    assert [record.record_id for record in selected.records] == ["a"]
    assert selected.statuses == {
        "selected": 1,
        "duplicate_source": 1,
        "test_source": 1,
        "invalid_compile_cmd": 1,
    }


def test_mechanical_source_clean_gates_and_emits_canonical_pair():
    parent = _parent("parent-1")
    verifier = MockVerifier(
        lambda src, cmd, path: ok_result() if src == CORRECT else _error_result()
    )

    outcome = mutate_real_source(
        parent,
        verifier,
        mutations=[DeleteSemicolon()],
        seed=23,
        max_candidates_per_mutation=1,
        max_verifications=4,
        max_records=2,
    )

    assert outcome.status == "accepted"
    assert outcome.baseline_compiles == 1
    assert outcome.mutant_compiles == 1
    assert outcome.candidates_selected == 1
    assert len(outcome.records) == 1
    record = outcome.records[0]
    assert record.corrected_src == CORRECT
    assert record.erroneous_src != CORRECT
    assert record.primary_diagnostic.file == "llvm/lib/A.cpp"
    assert record.provenance.origin is Origin.MUTATE
    assert record.provenance.source == parent.provenance.source
    assert record.provenance.detail["strategy"] == "mechanical_real_source"
    assert record.provenance.detail["mutation"] == "delete_semicolon"
    assert record.provenance.detail["compile_cmd"] == CMD
    assert record.provenance.detail["source_path"] == "llvm/lib/A.cpp"
    assert record.provenance.detail["seed"] == 23
    assert record.provenance.detail["parent_record_id"] == "parent-1"


def test_mechanical_source_rejects_nonclean_parent_before_mutation():
    verifier = MockVerifier(lambda src, cmd, path: _error_result("err_existing"))

    outcome = mutate_real_source(
        _parent("parent-1"),
        verifier,
        mutations=[DeleteSemicolon()],
        seed=0,
        max_candidates_per_mutation=3,
        max_verifications=3,
        max_records=3,
    )

    assert outcome.status == "corrected_not_clean"
    assert outcome.records == ()
    assert outcome.baseline_compiles == 1
    assert outcome.mutant_compiles == 0
    assert [rejection.status for rejection in outcome.rejections] == [
        "corrected_not_clean"
    ]
    assert len(verifier.call_log) == 1


def test_mechanical_source_records_clean_and_missing_diagnostic_rejections():
    calls = 0

    def policy(src, cmd, path):
        nonlocal calls
        calls += 1
        if calls <= 2:
            return ok_result()
        return VerifierResult(ok=False, diag=None, raw_stderr="__TIMEOUT__")

    outcome = mutate_real_source(
        _parent("parent-1"),
        MockVerifier(policy),
        mutations=[DeleteSemicolon()],
        seed=4,
        max_candidates_per_mutation=2,
        max_verifications=2,
        max_records=2,
    )

    assert outcome.status == "no_verified_mutants"
    assert [rejection.status for rejection in outcome.rejections] == [
        "mutant_clean", "timeout"
    ]
    assert outcome.mutant_compiles == 2


def test_mechanical_source_honors_compile_budget():
    outcome = mutate_real_source(
        _parent("parent-1"),
        MockVerifier(
            lambda src, cmd, path: ok_result() if src == CORRECT else _error_result()
        ),
        mutations=[DeleteSemicolon()],
        seed=1,
        max_candidates_per_mutation=3,
        max_verifications=1,
        max_records=3,
    )

    assert outcome.mutant_compiles == 1
    assert len(outcome.records) == 1
    assert any(
        rejection.status == "verification_cap"
        for rejection in outcome.rejections
    )
