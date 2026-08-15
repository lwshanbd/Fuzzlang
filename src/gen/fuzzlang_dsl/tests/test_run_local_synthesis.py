from __future__ import annotations

import json
from pathlib import Path

from gen.fuzzlang_dsl.injector import FuzzLangInjector
from gen.fuzzlang_dsl.local_gemma import DEFAULT_GEMMA_31B_REVISION
import pytest

from gen.fuzzlang_dsl.run_local_synthesis import (
    _write_jsonl,
    require_regression_test_evidence,
    run_synthesis_campaign,
    select_request_range,
    with_validation_feedback,
)
from gen.fuzzlang_dsl.synthesis import DiagnosticEvidence, SynthesisRequest
from repair.agent.chat_backend import ChatResponse, MockChatBackend


def _payload() -> dict:
    injector = FuzzLangInjector(
        target_diag="err_example",
        target_diag_id=17,
        language="c++",
        operation="insert",
        old_patterns=(),
        new_text="&",
        left_context=("return",),
        right_context=("<ID0>", ";"),
        portable=True,
        replacement_parts=(("literal", "&"),),
    )
    value = injector.to_dict()
    value.pop("injector_id")
    return value


def _payload_for(*, name: str, diag_id: int) -> dict:
    """Return a distinct valid Injector payload for a resumability test."""
    payload = _payload()
    payload["target"] = {
        "diag_name": name,
        "diag_id": diag_id,
    }
    return payload


def _fragment_payload() -> dict:
    injector = FuzzLangInjector.append_fragment(
        target_diag="err_example",
        diag_id=17,
        language="c++",
        fragment="namespace fuzzlang_generated { int trigger() { return &(int{0}); } }\n",
    )
    value = injector.to_dict()
    value.pop("injector_id")
    return value


def test_run_archives_raw_attempt_injector_and_no_api_manifest(tmp_path: Path):
    request = SynthesisRequest(
        diag_name="err_example",
        diag_id=17,
        diag_message="example error",
        component="Sema",
        language="c++",
        correct_snippets=(
            "int f(){int x=0; return x;}",
            "int g(){int y=1; return y;}",
        ),
    )
    backend = MockChatBackend([[
        ChatResponse(json.dumps(_payload()), 23),
        ChatResponse("not json", 4),
    ]])

    manifest = run_synthesis_campaign(
        (request,),
        backend,
        output_dir=tmp_path,
        model_name="google/gemma-4-31B-it",
        model_revision=DEFAULT_GEMMA_31B_REVISION,
        n_candidates=2,
        temperature=0.2,
        max_tokens=256,
    )

    assert manifest["model"]["role"] == "injector_synthesis"
    assert manifest["model"]["parameters"] == "31B"
    assert manifest["paid_api_calls"] is False
    assert manifest["counts"] == {
        "requests": 1,
        "candidates": 2,
            "accepted_candidates": 1,
            "unique_injectors": 1,
            "rejected_candidates": 1,
            "excluded_injector_identities": 0,
            "feedback_round_requests": 0,
    }
    rows = [json.loads(line) for line in
            (tmp_path / "attempts.jsonl").read_text().splitlines()]
    assert rows[0]["status"] == "accepted"
    assert rows[1]["reason"] == "json_object_not_found"
    injectors = (tmp_path / "injectors.jsonl").read_text().splitlines()
    assert len(injectors) == 1
    assert json.loads(injectors[0])["target"]["diag_name"] == "err_example"
    archived_requests = (tmp_path / "requests.jsonl").read_text().splitlines()
    assert len(archived_requests) == 1
    assert json.loads(archived_requests[0])["diag_id"] == 17
    disk_manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert disk_manifest["files"]["injectors.jsonl"]["sha256"]
    assert disk_manifest["files"]["requests.jsonl"]["sha256"]
    assert disk_manifest["execution"]["backend_class"] == "MockChatBackend"


def test_run_archives_v2_append_fragment_mode(tmp_path: Path):
    request = SynthesisRequest(
        diag_name="err_example", diag_id=17, diag_message="example error",
        component="Sema", language="c++",
        correct_snippets=("int f() { return 0; }", "int g() { return 1; }"),
    )
    backend = MockChatBackend([[
        ChatResponse(json.dumps(_fragment_payload()), 31),
    ]])

    manifest = run_synthesis_campaign(
        (request,), backend, output_dir=tmp_path,
        model_name="google/gemma-4-31B-it",
        model_revision=DEFAULT_GEMMA_31B_REVISION,
        synthesis_mode="fragment",
    )

    injector = FuzzLangInjector.from_json((tmp_path / "injectors.jsonl").read_text())
    assert injector.operation == "append"
    assert manifest["generation"]["synthesis_mode"] == "fragment"


def test_select_request_range_is_bounded_and_deterministic():
    requests = ("zero", "one", "two")

    assert select_request_range(requests, start=1, stop=3) == ("one", "two")
    assert select_request_range(requests, start=2) == ("two",)
    with pytest.raises(ValueError, match="start"):
        select_request_range(requests, start=-1)
    with pytest.raises(ValueError, match="stop"):
        select_request_range(requests, start=2, stop=4)


def test_regression_evidence_filter_keeps_only_test_grounded_requests():
    request = SynthesisRequest(
        diag_name="err_test_grounded", diag_id=1, diag_message="x",
        component="Sema", language="c++", correct_snippets=("int x;", "int y;"),
        evidence=DiagnosticEvidence(
            emission_evidence="Regression-test trigger evidence: expected-error"
        ),
    )
    no_test = SynthesisRequest(
        diag_name="err_no_test", diag_id=2, diag_message="y", component="Sema",
        language="c++", correct_snippets=("int y;", "int z;"),
    )

    assert require_regression_test_evidence((request, no_test)) == (request,)


def test_regression_evidence_filter_accepts_scan_derived_trigger_configuration():
    """A typed-diagnostic test scan is valid prompt-only trigger evidence."""
    request = SynthesisRequest(
        diag_name="err_scan_grounded", diag_id=3, diag_message="z",
        component="Sema", language="c++", correct_snippets=("int z;", "int q;"),
        evidence=DiagnosticEvidence(
            emission_evidence=(
                "Clang regression-test trigger evidence (not a dataset source):\n"
                "  -fsyntax-only -x c++ -std=c++23"
            ),
        ),
    )

    assert require_regression_test_evidence((request,)) == (request,)


def test_run_rejects_candidates_with_an_excluded_injector_identity(tmp_path: Path):
    request = SynthesisRequest(
        diag_name="err_example",
        diag_id=17,
        diag_message="example error",
        component="Sema",
        language="c++",
        correct_snippets=(
            "int f(){ int x=0; return x; }",
            "int g(){ int y=1; return y; }",
        ),
    )
    payload = _payload()
    excluded_id = FuzzLangInjector.from_dict(payload).injector_id
    backend = MockChatBackend([[ChatResponse(json.dumps(payload), 23)]])

    manifest = run_synthesis_campaign(
        (request,),
        backend,
        output_dir=tmp_path,
        model_name="google/gemma-4-31B-it",
        model_revision=DEFAULT_GEMMA_31B_REVISION,
        excluded_injector_ids=(excluded_id,),
    )

    assert manifest["counts"]["accepted_candidates"] == 0
    assert manifest["counts"]["unique_injectors"] == 0
    assert manifest["counts"]["rejected_candidates"] == 1
    attempt = json.loads((tmp_path / "attempts.jsonl").read_text())
    assert attempt["status"] == "rejected"
    assert attempt["reason"] == "duplicate_excluded_injector"


def test_campaign_retries_rejected_target_with_dsl_validation_feedback(tmp_path: Path):
    request = SynthesisRequest(
        diag_name="err_example",
        diag_id=17,
        diag_message="example error",
        component="Sema",
        language="c++",
        correct_snippets=(
            "int f(){int x=0; return x;}",
            "int g(){int y=1; return y;}",
        ),
    )
    backend = MockChatBackend([
        [ChatResponse("not JSON", 4)],
        [ChatResponse(json.dumps(_payload()), 23)],
    ])

    manifest = run_synthesis_campaign(
        (request,), backend, output_dir=tmp_path,
        model_name="google/gemma-4-31B-it",
        model_revision=DEFAULT_GEMMA_31B_REVISION,
        n_candidates=1, feedback_rounds=2,
    )

    attempts = [json.loads(line) for line in
                (tmp_path / "attempts.jsonl").read_text().splitlines()]
    assert [row["feedback_round"] for row in attempts] == [0, 1]
    assert manifest["counts"]["accepted_candidates"] == 1
    assert manifest["counts"]["feedback_round_requests"] == 1
    assert "DSL validation feedback" in backend.call_log[1]["messages"][1]["content"]


def test_campaign_microbatches_distinct_requests_through_backend(tmp_path: Path):
    requests = tuple(
        SynthesisRequest(
            diag_name="err_example",
            diag_id=17,
            diag_message="example error",
            component="Sema",
            language="c++",
            correct_snippets=(
                "int f(){int x=0; return x;}",
                "int g(){int y=1; return y;}",
            ),
        )
        for _ in range(2)
    )

    class _WideBackend:
        def __init__(self):
            self.batch_sizes: list[int] = []
            self.chat_calls = 0

        def chat(self, **_kwargs):
            self.chat_calls += 1
            raise AssertionError("first synthesis round must be microbatched")

        def chat_batch(self, *, messages_batch, n, **_kwargs):
            self.batch_sizes.append(len(messages_batch))
            assert n == 1
            return [[ChatResponse(json.dumps(_payload()), 23)] for _ in messages_batch]

    backend = _WideBackend()
    manifest = run_synthesis_campaign(
        requests, backend, output_dir=tmp_path,
        model_name="google/gemma-4-31B-it",
        model_revision=DEFAULT_GEMMA_31B_REVISION,
        request_batch_size=2,
    )

    assert backend.batch_sizes == [2]
    assert backend.chat_calls == 0
    assert manifest["generation"]["request_batch_size"] == 2
    assert manifest["counts"]["accepted_candidates"] == 2


def test_campaign_resume_keeps_completed_requests_and_only_queries_the_tail(
    tmp_path: Path,
):
    """A timed GPU allocation must not regenerate a checkpointed Injector."""
    first = SynthesisRequest(
        diag_name="err_first", diag_id=17, diag_message="first",
        component="Sema", language="c++",
        correct_snippets=(
            "int f(){int first = 0; return first;}",
            "int g(){int second = 1; return second;}",
        ),
    )
    second = SynthesisRequest(
        diag_name="err_second", diag_id=18, diag_message="second",
        component="Sema", language="c++",
        correct_snippets=(
            "int h(){int third = 2; return third;}",
            "int i(){int fourth = 3; return fourth;}",
        ),
    )

    class _InterruptingBackend:
        def __init__(self) -> None:
            self.calls = 0

        def chat(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return [ChatResponse(json.dumps(_payload_for(
                    name="err_first", diag_id=17,
                )), 23)]
            raise RuntimeError("allocation expired")

    with pytest.raises(RuntimeError, match="allocation expired"):
        run_synthesis_campaign(
            (first, second), _InterruptingBackend(), output_dir=tmp_path,
            model_name="google/gemma-4-31B-it",
            model_revision=DEFAULT_GEMMA_31B_REVISION,
        )

    resumed_backend = MockChatBackend([[
        ChatResponse(json.dumps(_payload_for(name="err_second", diag_id=18)), 23),
    ]])
    manifest = run_synthesis_campaign(
        (first, second), resumed_backend, output_dir=tmp_path,
        model_name="google/gemma-4-31B-it",
        model_revision=DEFAULT_GEMMA_31B_REVISION,
        resume=True,
    )

    assert len(resumed_backend.call_log) == 1
    assert manifest["counts"]["requests"] == 2
    assert manifest["counts"]["unique_injectors"] == 2
    attempts = [json.loads(line) for line in
                (tmp_path / "attempts.jsonl").read_text().splitlines()]
    assert [row["request_index"] for row in attempts] == [0, 1]


def test_validation_feedback_preserves_the_real_source_snippets():
    request = SynthesisRequest(
        diag_name="err_example",
        diag_id=17,
        diag_message="example error",
        component="Sema",
        language="c++",
        correct_snippets=("int f(){return 0;}", "int g(){return 1;}"),
    )

    revised = with_validation_feedback(
        request, rejection_reasons=("no_exemplar_match",),
    )

    assert revised.correct_snippets == request.correct_snippets
    assert "no_exemplar_match" in revised.evidence.emission_evidence


def test_jsonl_checkpoint_is_written_to_a_temp_path_before_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    target = tmp_path / "injectors.jsonl"
    writes: list[Path] = []
    original_write_text = Path.write_text

    def record_write(self: Path, *args, **kwargs):
        writes.append(self)
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", record_write)
    _write_jsonl(target, ({"target": "err_example"},))

    assert target not in writes
    assert len(writes) == 1
    assert writes[0].name.startswith(".injectors.jsonl.")
    assert target.read_text() == '{"target":"err_example"}\n'


def test_tioga_synthesis_cleanup_does_not_wait_forever_for_launcher():
    script = Path("src/gen/fuzzlang_dsl/run_tioga_vllm_synthesis.sh").read_text()

    assert "cleanup must not block waiting for the container launcher" in script
