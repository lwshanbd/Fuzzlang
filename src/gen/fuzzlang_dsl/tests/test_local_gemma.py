from __future__ import annotations

import json
from pathlib import Path

import pytest

from gen.fuzzlang_dsl.local_gemma import (
    DEFAULT_GEMMA_31B_MODEL,
    DEFAULT_GEMMA_31B_REVISION,
    flatten_messages_for_gemma,
    load_request_file,
    require_gemma_31b,
)


def test_synthesis_runner_is_pinned_to_largest_local_gemma():
    assert DEFAULT_GEMMA_31B_MODEL == "google/gemma-4-31B-it"
    assert DEFAULT_GEMMA_31B_REVISION == (
        "518276fb130dc81caf9a4f772e65e63ef2526493"
    )
    require_gemma_31b(DEFAULT_GEMMA_31B_MODEL)
    require_gemma_31b(
        "/cache/models--google--gemma-4-31B-it/snapshots/revision"
    )


@pytest.mark.parametrize(
    "model",
    ["google/gemma-4-4b-it", "google/gemma-3-27b-it", "gemma-small"],
)
def test_synthesis_runner_rejects_smaller_or_different_models(model: str):
    with pytest.raises(ValueError, match="Gemma-4-31B-it"):
        require_gemma_31b(model)


def test_flatten_messages_preserves_system_and_user_in_one_supported_turn():
    messages = [
        {"role": "system", "content": "Return one Injector JSON."},
        {"role": "user", "content": "Target err_example."},
    ]

    flattened = flatten_messages_for_gemma(messages)

    assert flattened == [
        {
            "role": "user",
            "content": [{
                "type": "text",
                "text": (
                    "SYSTEM INSTRUCTION:\nReturn one Injector JSON.\n\n"
                    "USER TASK:\nTarget err_example."
                ),
            }],
        }
    ]


def test_load_request_file_accepts_jsonl_and_validates_evidence(tmp_path: Path):
    path = tmp_path / "requests.jsonl"
    row = {
        "diag_name": "err_example",
        "diag_id": 17,
        "diag_message": "example error",
        "component": "Sema",
        "language": "c++",
        "tablegen_definition": "def err_example : Error<...>;",
        "emission_evidence": "SemaExample.cpp:42",
        "correct_snippets": ["int f() { return 0; }", "int g() { return 1; }"],
    }
    path.write_text(json.dumps(row) + "\n")

    requests = load_request_file(path)

    assert len(requests) == 1
    assert requests[0].diag_name == "err_example"
    assert requests[0].evidence.tablegen_definition.startswith("def err_example")
    assert requests[0].correct_snippets[1].startswith("int g")
