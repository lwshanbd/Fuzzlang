from __future__ import annotations

import json

from gen.fuzzlang_dsl.code_witness import CodeWitnessRequest
from gen.fuzzlang_dsl.e1_experiment import (
    E1Budget, run_direct_edit_arm, run_injector_arm,
)
from gen.fuzzlang_dsl.synthesis import _machine_checked_match_shapes
from foundation.types import DiagInfo
from repair.agent.chat_backend import ChatResponse

CLEAN = "int main() { return 0; }\nint helper() { return 1; }\n"


class _Verifier:
    """Compile stub: sources containing MARKER fail with the target diagnostic."""

    def __init__(self, marker: str = "BROKEN", diag_name: str = "err_target",
                 diag_id: int = 17, wrong_for: str = "WRONG") -> None:
        self.marker, self.diag_name, self.diag_id = marker, diag_name, diag_id
        self.wrong_for = wrong_for
        self.calls = 0

    def verify(self, source, compile_cmd, *, logical_path):
        self.calls += 1
        if self.wrong_for in source:
            return _Result(False, self._diag("err_other", 99, logical_path))
        if self.marker in source:
            return _Result(False, self._diag(self.diag_name, self.diag_id, logical_path))
        return _Result(True, None)

    def _diag(self, name, diag_id, path):
        return DiagInfo(
            diag_id=diag_id, diag_name=name, diag_msg=name, file=path,
            line=1, col=1, start_byte=0, end_byte=1, span_snippet="x",
        )


class _Result:
    def __init__(self, ok, diag):
        self.ok, self.diag = ok, diag


class _Backend:
    """Replay a fixed script of responses and count calls/tokens."""

    def __init__(self, texts: list[str]) -> None:
        self.texts, self.calls = texts, 0

    def chat(self, *, messages, temperature, max_tokens, n=1, response_format=None):
        text = self.texts[min(self.calls, len(self.texts) - 1)]
        self.calls += 1
        return [ChatResponse(text=text, output_tokens=11) for _ in range(n)]


def _request(source_id: str, project: str = "llvm") -> CodeWitnessRequest:
    return CodeWitnessRequest(
        diag_name="err_target",
        diag_id=17,
        diag_message="target",
        language="c++",
        tablegen_definition='def err_target : Error<"target">;',
        source_id=f"{project}:{source_id}",
        source_path=source_id,
        project=project,
        compile_cmd=("__CLANG__", "-std=c++23", "__SRC__"),
        corrected_src=CLEAN,
        window_start=0,
        window_end=len(CLEAN),
        component="Sema",
    )


def test_direct_edit_arm_accepts_only_the_exact_requested_diagnostic():
    requests = {"err_target": [_request("a.cpp"), _request("b.cpp")]}
    backend = _Backend([json.dumps({"old_text": "return 0", "new_text": "BROKEN"})])
    verifier = _Verifier()

    result = run_direct_edit_arm(
        requests, backend, verifier, candidates=1, temperature=0.0,
        max_tokens=64,
    )

    assert len(result.records) == 2
    assert all(r.corrected_src == CLEAN for r in result.records)
    assert all(
        r.provenance.detail["strategy"] == "gemma_localized_direct_edit"
        for r in result.records
    )
    assert result.budget.model_calls == 2
    assert result.budget.output_tokens == 22
    assert result.per_target["err_target"]["accepted_records"] == 2
    assert result.per_target["err_target"]["attempted_sources"] == 2


def test_direct_edit_arm_rejects_a_wrong_primary_diagnostic_with_a_reason():
    requests = {"err_target": [_request("a.cpp")]}
    backend = _Backend([json.dumps({"old_text": "return 0", "new_text": "WRONG"})])

    result = run_direct_edit_arm(
        requests, _Backend(backend.texts), _Verifier(), candidates=1,
        temperature=0.0, max_tokens=64,
    )

    assert result.records == []
    reasons = [a.reason for a in result.attempts if a.status == "rejected"]
    assert reasons == ["wrong_primary_diagnostic"]
    assert [a.observed_diag for a in result.attempts] == ["err_other"]
    assert result.per_target["err_target"]["accepted_records"] == 0


def test_direct_edit_arm_never_admits_a_clean_mutant():
    requests = {"err_target": [_request("a.cpp")]}
    backend = _Backend([json.dumps({"old_text": "return 0", "new_text": "return 2"})])

    result = run_direct_edit_arm(
        requests, backend, _Verifier(), candidates=1, temperature=0.0,
        max_tokens=64,
    )

    assert result.records == []
    assert [a.reason for a in result.attempts] == ["mutant_compiles_clean"]


def _injector_payload(literal: str) -> str:
    """A schema-valid lexical insert Injector for the shared CLEAN window."""
    shapes = _machine_checked_match_shapes((CLEAN,))
    return json.dumps({
        "schema": "fuzzlang.injector",
        "schema_version": 1,
        "target": {"diag_name": "err_target", "diag_id": 17},
        "language": "c++",
        "match": {"left_context": [], "old_patterns": [], "right_context": []},
        "edit": {
            "operation": "insert",
            "replacement_parts": [{"kind": "literal", "value": literal}],
            "exemplar_replacement": literal,
        },
        "portable": True,
        "limits": {
            "max_edit_chars": 256, "max_candidates": 8, "max_verifications": 50,
        },
        "provenance": {
            "source_recipe_id": None, "support": 1, "exemplar_ids": [],
        },
        "match_selection": {
            "shape_index": 0,
            "edit_start": len(shapes[0]),
            "edit_end": len(shapes[0]),
        },
    })


def test_injector_arm_amortizes_one_model_call_over_every_source():
    sources = [_request("a.cpp"), _request("b.cpp"), _request("c.cpp", "abseil")]
    backend = _Backend([_injector_payload(" BROKEN ")])
    verifier = _Verifier()

    result = run_injector_arm(
        {"err_target": sources}, backend, verifier, candidates=1,
        temperature=0.0, max_tokens=256, evidence_sources=2,
    )

    assert result.budget.model_calls == 1
    assert len(result.records) == 3
    assert {r.provenance.detail["project"] for r in result.records} == {
        "llvm", "abseil",
    }
    assert all(
        r.provenance.detail["strategy"] == "e1_injector_replay"
        for r in result.records
    )
    stats = result.per_target["err_target"]
    assert stats["accepted_records"] == 3
    assert stats["replay_sources"] == 3
    assert stats["transfer_sources"] == 1
    assert stats["accepted_injectors"] == 1
    assert len(result.injectors) == 1


def test_injector_arm_reports_a_target_whose_injector_never_replays():
    sources = [_request("a.cpp"), _request("b.cpp")]
    backend = _Backend([_injector_payload(" ")])

    result = run_injector_arm(
        {"err_target": sources}, backend, _Verifier(), candidates=1,
        temperature=0.0, max_tokens=256, evidence_sources=2,
    )

    assert result.records == []
    assert result.per_target["err_target"]["accepted_injectors"] == 1
    assert result.per_target["err_target"]["replaying_injectors"] == 0
    assert {a.reason for a in result.attempts if a.status == "rejected"} == {
        "mutant_compiles_clean",
    }


def test_fanning_out_over_targets_preserves_every_arm_total():
    payload = json.dumps({"old_text": "return 0", "new_text": "BROKEN"})
    requests = {
        f"err_target{index}": [_request(f"{index}a.cpp"), _request(f"{index}b.cpp")]
        for index in range(4)
    }
    for target, items in requests.items():
        requests[target] = [
            CodeWitnessRequest(**{**item.to_dict(), "diag_name": "err_target"})
            for item in items
        ]

    serial = run_direct_edit_arm(
        requests, _Backend([payload]), _Verifier(), candidates=1,
        temperature=0.0, max_tokens=64, max_workers=1,
    )
    parallel = run_direct_edit_arm(
        requests, _Backend([payload]), _Verifier(), candidates=1,
        temperature=0.0, max_tokens=64, max_workers=4,
    )

    assert parallel.budget.to_dict()["model_calls"] == serial.budget.to_dict()["model_calls"] == 8
    assert len(parallel.records) == len(serial.records) == 8
    assert [r.record_id for r in parallel.records] == [r.record_id for r in serial.records]
    assert set(parallel.per_target) == set(serial.per_target)


class _FlakyBackend:
    """Fail the first model call, then behave normally."""

    def __init__(self, text: str) -> None:
        self.text, self.calls = text, 0

    def chat(self, *, messages, temperature, max_tokens, n=1, response_format=None):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("vLLM HTTP 404: model does not exist")
        return [ChatResponse(text=self.text, output_tokens=11) for _ in range(n)]


def test_one_failed_model_call_does_not_abort_the_arm():
    """A transient endpoint error must cost one source, not the whole run."""
    requests = {"err_target": [_request("a.cpp"), _request("b.cpp")]}
    backend = _FlakyBackend(json.dumps({"old_text": "return 0", "new_text": "BROKEN"}))

    result = run_direct_edit_arm(
        requests, backend, _Verifier(), candidates=1, temperature=0.0,
        max_tokens=64,
    )

    assert len(result.records) == 1
    failures = [a for a in result.attempts if a.reason == "model_call_failed"]
    assert len(failures) == 1
    assert "404" in failures[0].response_text
    assert result.per_target["err_target"]["failed_model_calls"] == 1


def test_a_failed_injector_synthesis_call_is_recorded_not_raised():
    requests = {"err_target": [_request("a.cpp"), _request("b.cpp")]}

    result = run_injector_arm(
        requests, _FlakyBackend("{}"), _Verifier(), candidates=1,
        temperature=0.0, max_tokens=256, evidence_sources=2,
    )

    assert result.records == []
    assert result.per_target["err_target"]["failed_model_calls"] == 1
    assert [a.reason for a in result.attempts] == ["model_call_failed"]


def test_budget_reports_records_per_output_token_and_gpu_hour():
    budget = E1Budget(
        model_calls=4, prompt_tokens=100, output_tokens=2_000,
        model_seconds=3_600.0, compiler_invocations=12,
    )

    summary = budget.efficiency(accepted_records=8)

    assert summary["records_per_1k_output_tokens"] == 4.0
    assert summary["records_per_gpu_hour"] == 8.0
    assert summary["compiler_invocations_per_accepted_record"] == 1.5


def test_budget_efficiency_is_defined_when_nothing_was_accepted():
    budget = E1Budget(model_calls=1, output_tokens=10, model_seconds=1.0)

    summary = budget.efficiency(accepted_records=0)

    assert summary["records_per_1k_output_tokens"] == 0.0
    assert summary["compiler_invocations_per_accepted_record"] is None


def test_direct_edit_records_carry_canonical_directedit_provenance():
    """The SFT arm builder identifies a DirectEdit record by its provenance.

    A per-record localized model edit verified by the compiler is exactly what
    `llm_localized_edit` denotes, so this path must be labelled that way to be
    usable as the equal-budget data baseline in E3.
    """
    requests = {"err_target": [_request("a.cpp")]}
    backend = _Backend([json.dumps({"old_text": "return 0", "new_text": "BROKEN"})])

    result = run_direct_edit_arm(
        requests, backend, _Verifier(), candidates=1, temperature=0.0,
        max_tokens=64,
    )

    detail = result.records[0].provenance.detail
    assert result.records[0].provenance.origin.value == "llm"
    assert detail["generator"] == "llm_localized_edit"
    assert detail["strategy"] == "gemma_localized_direct_edit"
    assert detail["target_diag"] == "err_target"
    assert detail["primary_matches_target"] is True


def test_injector_arm_records_keep_mutate_origin():
    """Only the per-record model edit is an LLM-origin record."""
    sources = [_request("a.cpp"), _request("b.cpp")]
    result = run_injector_arm(
        {"err_target": sources}, _Backend([_injector_payload(" BROKEN ")]),
        _Verifier(), candidates=1, temperature=0.0, max_tokens=256,
        evidence_sources=2,
    )

    assert result.records[0].provenance.origin.value == "mutate"
