"""Orchestration tests for gen.collect using MockVerifier (no real compiler).

collect_records is where the correct-code invariant lands: it keeps a mutant
only when the *original* source compiles cleanly AND the mutated source triggers
a real error diagnostic. The corrected_src of every emitted record is the
original correct source.
"""
from __future__ import annotations

from foundation.record import Origin, Split
from foundation.types import DiagInfo, VerifierResult
from foundation.verifier.mock import MockVerifier, ok_result
from gen.collect import collect_records
from gen.mutate.delete_semicolon import DeleteSemicolon

CORRECT = "int main() { int x = 1; return 0; }"


def _err(diag_name="err_expected_semi_declaration", diag_id=1650):
    return VerifierResult(
        ok=False,
        diag=DiagInfo(
            diag_id=diag_id, diag_name=diag_name, diag_msg="expected ';'",
            file="unit:test", line=1, col=10, start_byte=0, end_byte=1,
            span_snippet="x",
        ),
        raw_stderr="error: expected ';'\nDiagID: %d\n" % diag_id,
    )


def _break_only_original_ok(src, cmd, lp):
    return ok_result() if src == CORRECT else _err()


def test_emits_record_for_a_breaking_mutant():
    v = MockVerifier(_break_only_original_ok)
    records = collect_records(CORRECT, v, source="unit:test",
                              mutations=[DeleteSemicolon()])
    assert records, "expected at least one record"
    r = records[0]
    assert r.provenance.origin is Origin.MUTATE
    assert r.split is Split.TRAIN
    assert r.corrected_src == CORRECT          # the invariant: corrected = the correct origin
    assert r.erroneous_src != CORRECT
    assert r.primary_diagnostic.diag_name == "err_expected_semi_declaration"
    assert r.provenance.source == "unit:test"
    assert r.provenance.detail["mutation"] == "delete_semicolon"


def test_returns_empty_when_original_does_not_compile():
    # If even the "correct" source fails, we cannot form a valid pair.
    v = MockVerifier(lambda src, cmd, lp: _err())
    records = collect_records(CORRECT, v, source="x",
                              mutations=[DeleteSemicolon()])
    assert records == []


def test_drops_mutants_that_still_compile():
    # Original ok, and every mutant also compiles -> nothing kept.
    v = MockVerifier(lambda src, cmd, lp: ok_result())
    records = collect_records(CORRECT, v, source="x",
                              mutations=[DeleteSemicolon()])
    assert records == []


def test_drops_errors_without_a_diagnostic():
    def policy(src, cmd, lp):
        if src == CORRECT:
            return ok_result()
        return VerifierResult(ok=False, diag=None, raw_stderr="ld: link error")
    records = collect_records(CORRECT, MockVerifier(policy), source="x",
                              mutations=[DeleteSemicolon()])
    assert records == []


def test_record_ids_are_unique():
    v = MockVerifier(_break_only_original_ok)
    records = collect_records(CORRECT, v, source="unit:test",
                              mutations=[DeleteSemicolon()])
    ids = [r.record_id for r in records]
    assert len(ids) == len(set(ids))


def test_default_mutations_run_when_none_given():
    # CORRECT has semicolons, braces, parens -> several text mutations fire.
    v = MockVerifier(_break_only_original_ok)
    records = collect_records(CORRECT, v, source="unit:test")
    kinds = {r.provenance.detail["mutation"] for r in records}
    assert "delete_semicolon" in kinds
    assert "delete_bracket" in kinds
