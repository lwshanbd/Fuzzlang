from __future__ import annotations

import json
from pathlib import Path

from gen.fuzzlang_dsl.injector import FuzzLangInjector
from gen.fuzzlang_dsl.local_gemma import DEFAULT_GEMMA_31B_REVISION
import pytest

from gen.fuzzlang_dsl.run_local_synthesis import (
    run_synthesis_campaign,
    select_request_range,
)
from gen.fuzzlang_dsl.synthesis import SynthesisRequest
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


def test_select_request_range_is_bounded_and_deterministic():
    requests = ("zero", "one", "two")

    assert select_request_range(requests, start=1, stop=3) == ("one", "two")
    assert select_request_range(requests, start=2) == ("two",)
    with pytest.raises(ValueError, match="start"):
        select_request_range(requests, start=-1)
    with pytest.raises(ValueError, match="stop"):
        select_request_range(requests, start=2, stop=4)


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
