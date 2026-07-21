"""Offline Gemma-4-31B backend for diagnostic-to-Injector synthesis.

This module is intentionally separate from SFT.  Injector synthesis is a
reasoning-heavy compiler task and is pinned to the largest locally staged
Gemma model; fine-tuning code remains free to use smaller models.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from gen.fuzzlang_dsl.synthesis import (
    DiagnosticEvidence,
    SynthesisRequest,
)
from repair.agent.chat_backend import ChatResponse


DEFAULT_GEMMA_31B_MODEL = "google/gemma-4-31B-it"
DEFAULT_GEMMA_31B_REVISION = "518276fb130dc81caf9a4f772e65e63ef2526493"
DEFAULT_GEMMA_31B_SNAPSHOT = Path(
    "/p/lustre1/shan4/gemma/hf/hub/"
    "models--google--gemma-4-31B-it/snapshots/"
    + DEFAULT_GEMMA_31B_REVISION
)


def require_gemma_31b(model_name_or_path: str | Path) -> None:
    """Reject accidental use of a smaller model for Injector synthesis."""
    normalized = str(model_name_or_path).lower()
    if "gemma-4-31b-it" not in normalized:
        raise ValueError(
            "Injector synthesis requires the local Gemma-4-31B-it model; "
            f"got {model_name_or_path!s}"
        )


def flatten_messages_for_gemma(
    messages: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Merge system/user text into one Gemma-compatible user turn.

    The staged Gemma chat template is most reliable with list-of-parts content
    and does not need a separate system role.  Role labels preserve the
    instruction boundary inside that single turn.
    """
    sections: list[str] = []
    labels = {
        "system": "SYSTEM INSTRUCTION",
        "user": "USER TASK",
        "assistant": "ASSISTANT CONTEXT",
    }
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if not isinstance(content, str):
            raise ValueError("Gemma synthesis messages must contain text")
        sections.append(f"{labels.get(role, role.upper())}:\n{content}")
    text = "\n\n".join(sections)
    return [{
        "role": "user",
        "content": [{"type": "text", "text": text}],
    }]


def _request_from_dict(value: dict[str, Any]) -> SynthesisRequest:
    evidence = value.get("evidence") or {}
    if not isinstance(evidence, dict):
        raise ValueError("request evidence must be an object")
    return SynthesisRequest(
        diag_name=value["diag_name"],
        diag_id=value.get("diag_id"),
        diag_message=value["diag_message"],
        component=value["component"],
        language=value["language"],
        correct_snippets=tuple(value["correct_snippets"]),
        evidence=DiagnosticEvidence(
            tablegen_definition=value.get(
                "tablegen_definition", evidence.get("tablegen_definition")
            ),
            emission_evidence=value.get(
                "emission_evidence", evidence.get("emission_evidence")
            ),
        ),
    )


def load_request_file(path: Path) -> tuple[SynthesisRequest, ...]:
    """Load one JSON object/list or newline-delimited synthesis requests."""
    text = Path(path).read_text()
    stripped = text.lstrip()
    if not stripped:
        return ()
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        values = [
            json.loads(line) for line in text.splitlines() if line.strip()
        ]
    else:
        if isinstance(decoded, list):
            values = decoded
        elif isinstance(decoded, dict):
            values = [decoded]
        else:
            raise ValueError("request JSON must contain an object or list")
    if any(not isinstance(value, dict) for value in values):
        raise ValueError("every synthesis request must be a JSON object")
    return tuple(_request_from_dict(value) for value in values)


class LocalGemma31BBackend:
    """Lazy Hugging Face backend sharded over all visible local GPUs."""

    def __init__(
        self,
        model_path: str | Path = DEFAULT_GEMMA_31B_SNAPSHOT,
        *,
        attn_implementation: str = "sdpa",
        seed: int = 0,
    ) -> None:
        require_gemma_31b(model_path)
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError("seed must be a non-negative integer")
        self.model_path = str(model_path)
        self.attn_implementation = attn_implementation
        self.seed = seed
        self._tokenizer = None
        self._model = None
        self._torch = None

    def _ensure_tokenizer(self):
        if self._tokenizer is None:
            from transformers import AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(
                self.model_path, local_files_only=True,
            )
        return self._tokenizer

    def _ensure_model(self):
        tokenizer = self._ensure_tokenizer()
        if self._model is None:
            import torch
            from transformers import AutoModelForCausalLM

            self._torch = torch
            try:
                self._model = AutoModelForCausalLM.from_pretrained(
                    self.model_path,
                    dtype=torch.bfloat16,
                    device_map="auto",
                    attn_implementation=self.attn_implementation,
                    local_files_only=True,
                )
            except Exception:
                if self.attn_implementation == "eager":
                    raise
                self._model = AutoModelForCausalLM.from_pretrained(
                    self.model_path,
                    dtype=torch.bfloat16,
                    device_map="auto",
                    attn_implementation="eager",
                    local_files_only=True,
                )
            self._model.eval()
        return tokenizer, self._model, self._torch

    def _tokenize(self, messages: list[dict[str, str]]):
        tokenizer = self._ensure_tokenizer()
        chat = flatten_messages_for_gemma(messages)
        try:
            return tokenizer.apply_chat_template(
                chat,
                add_generation_prompt=True,
                tokenize=True,
                return_tensors="pt",
                return_dict=True,
            )
        except Exception:
            plain = [{
                "role": "user",
                "content": chat[0]["content"][0]["text"],
            }]
            return tokenizer.apply_chat_template(
                plain,
                add_generation_prompt=True,
                tokenize=True,
                return_tensors="pt",
                return_dict=True,
            )

    def count_prompt_tokens(self, messages: list[dict[str, str]]) -> int:
        return int(self._tokenize(messages)["input_ids"].shape[-1])

    def chat(
        self,
        *,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        n: int = 1,
        response_format: Optional[dict[str, Any]] = None,
    ) -> list[ChatResponse]:
        """Generate locally; ``response_format`` is enforced after decoding."""
        del response_format
        if n > 1 and temperature <= 0:
            raise ValueError("multiple Gemma candidates require temperature > 0")
        tokenizer, model, torch = self._ensure_model()
        inputs = self._tokenize(messages)
        inputs = {key: value.to(model.device) for key, value in inputs.items()}
        input_tokens = int(inputs["input_ids"].shape[-1])
        generation: dict[str, Any] = {
            "max_new_tokens": max_tokens,
            "do_sample": temperature > 0,
            "num_return_sequences": n,
        }
        if temperature > 0:
            generation["temperature"] = temperature
        torch.manual_seed(self.seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(self.seed)
        with torch.inference_mode():
            outputs = model.generate(**inputs, **generation)
        responses: list[ChatResponse] = []
        for output in outputs:
            generated = output[input_tokens:]
            responses.append(ChatResponse(
                text=tokenizer.decode(generated, skip_special_tokens=True),
                output_tokens=int(generated.shape[-1]),
            ))
        return responses
