from __future__ import annotations

import json
from pathlib import Path

import pytest

from gen.fuzzlang_dsl.local_gemma import (
    DEFAULT_GEMMA_31B_MODEL,
    DEFAULT_GEMMA_31B_REVISION,
    LocalGemma31BBackend,
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


def test_local_gemma_batches_distinct_prompts_in_one_generate_call(monkeypatch):
    torch = pytest.importorskip("torch")

    class _Tokenizer:
        def apply_chat_template(self, chat, *, tokenize, **kwargs):
            assert tokenize is False
            return chat[0]["content"][0]["text"]

        def __call__(self, prompts, *, padding, return_tensors):
            assert padding is True
            assert return_tensors == "pt"
            assert len(prompts) == 2
            return {
                "input_ids": torch.tensor([[1, 2], [3, 4]]),
                "attention_mask": torch.tensor([[1, 1], [1, 1]]),
            }

        def decode(self, tokens, *, skip_special_tokens):
            assert skip_special_tokens is True
            return str(int(tokens[0]))

    class _Model:
        device = torch.device("cpu")

        def __init__(self):
            self.calls = 0

        def generate(self, **kwargs):
            self.calls += 1
            assert kwargs["input_ids"].shape == (2, 2)
            return torch.tensor([[1, 2, 10], [3, 4, 20]])

    model = _Model()
    backend = LocalGemma31BBackend(seed=7)
    monkeypatch.setattr(
        backend, "_ensure_model", lambda: (_Tokenizer(), model, torch),
    )

    responses = backend.chat_batch(
        messages_batch=[
            [{"role": "user", "content": "first"}],
            [{"role": "user", "content": "second"}],
        ],
        temperature=0.0,
        max_tokens=8,
    )

    assert model.calls == 1
    assert [[item.text for item in group] for group in responses] == [["10"], ["20"]]
