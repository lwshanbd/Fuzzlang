#!/usr/bin/env python3
"""Synthesize and archive FuzzLang Injectors with local Gemma-4-31B-it."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Sequence, TypeVar
from uuid import uuid4

from gen.fuzzlang_dsl.injector import FuzzLangInjector
from gen.fuzzlang_dsl.local_gemma import (
    DEFAULT_GEMMA_31B_MODEL,
    DEFAULT_GEMMA_31B_REVISION,
    DEFAULT_GEMMA_31B_SNAPSHOT,
    LocalGemma31BBackend,
    load_request_file,
    require_gemma_31b,
)
from gen.fuzzlang_dsl.regression_evidence import has_regression_trigger_evidence
from gen.fuzzlang_dsl.synthesis import (
    DiagnosticEvidence, SynthesisRequest, build_synthesis_messages,
    build_fragment_synthesis_messages, synthesize_fragment_injectors,
    synthesize_injectors, validate_fragment_synthesis_responses,
    validate_synthesis_responses,
)
from repair.agent.chat_backend import ChatBackend, VLLMChatBackend


_RequestT = TypeVar("_RequestT")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    )


def _write_jsonl(path: Path, values: Iterable[dict[str, Any]]) -> None:
    """Atomically publish a checkpoint so readers never observe partial JSONL."""
    payload = "".join(_canonical_json(value) + "\n" for value in values)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(payload)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _file_metadata(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "rows": sum(1 for line in payload.splitlines() if line.strip()),
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load an atomic JSONL checkpoint and reject malformed rows early."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{line_number}: invalid checkpoint JSON") from error
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{line_number}: checkpoint row must be an object")
        rows.append(row)
    return rows


def _request_dict(request: SynthesisRequest) -> dict[str, Any]:
    return {
        "diag_name": request.diag_name,
        "diag_id": request.diag_id,
        "diag_message": request.diag_message,
        "component": request.component,
        "language": request.language,
        "evidence": {
            "tablegen_definition": request.evidence.tablegen_definition,
            "emission_evidence": request.evidence.emission_evidence,
        },
        "correct_snippets": list(request.correct_snippets),
    }


def select_request_range(
    requests: Sequence[_RequestT], *, start: int = 0, stop: int | None = None,
) -> tuple[_RequestT, ...]:
    """Select a deterministic, bounded request shard for a timed GPU run."""
    if start < 0 or start > len(requests):
        raise ValueError("request start must fall within the input range")
    resolved_stop = len(requests) if stop is None else stop
    if resolved_stop < start or resolved_stop > len(requests):
        raise ValueError("request stop must fall within the input range and follow start")
    return tuple(requests[start:resolved_stop])


def require_regression_test_evidence(
    requests: Sequence[SynthesisRequest],
) -> tuple[SynthesisRequest, ...]:
    """Keep only targets whose prompt contains Clang regression-test evidence.

    The test snippet remains prompt-only evidence.  It never becomes a dataset
    source; replay still operates exclusively on paired clean production code.
    """
    return tuple(
        request for request in requests
        if has_regression_trigger_evidence(request.evidence.emission_evidence)
    )


def with_validation_feedback(
    request: SynthesisRequest, *, rejection_reasons: Sequence[str],
) -> SynthesisRequest:
    """Ask a later synthesis round to repair locally observed DSL failures."""
    reasons = sorted({reason for reason in rejection_reasons if reason})
    if not reasons:
        return request
    feedback = (
        "FuzzLang DSL validation feedback from prior candidates: "
        + "; ".join(reasons)
        + ". Revise the Injector instead of repeating those forms. In particular, "
        "copy one contiguous token shape exactly from a supplied correct snippet "
        "so the matcher has at least one concrete exemplar application."
    )
    existing = request.evidence.emission_evidence
    return replace(
        request,
        evidence=DiagnosticEvidence(
            tablegen_definition=request.evidence.tablegen_definition,
            emission_evidence=(
                feedback if existing is None else existing + "\n\n" + feedback
            ),
        ),
    )


def run_synthesis_campaign(
    requests: tuple[SynthesisRequest, ...],
    backend: ChatBackend,
    *,
    output_dir: Path,
    model_name: str,
    model_revision: str,
    n_candidates: int = 1,
    temperature: float = 0.2,
    max_tokens: int = 1200,
    feedback_rounds: int = 1,
    request_batch_size: int = 1,
    synthesis_mode: str = "lexical",
    excluded_injector_ids: Iterable[str] = (),
    resume: bool = False,
) -> dict[str, Any]:
    """Run bounded synthesis and preserve every raw/validated outcome."""
    require_gemma_31b(model_name)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    requests_path = output_dir / "requests.jsonl"
    attempts_path = output_dir / "attempts.jsonl"
    injectors_path = output_dir / "injectors.jsonl"
    request_rows = [_request_dict(item) for item in requests]
    if resume:
        archived_requests = _read_jsonl(requests_path)
        if archived_requests and archived_requests != request_rows:
            raise ValueError(
                "resume checkpoint requests do not match this bounded synthesis shard"
            )
        if not archived_requests:
            _write_jsonl(requests_path, request_rows)
        attempts = _read_jsonl(attempts_path)
        injector_rows = _read_jsonl(injectors_path)
        injectors = {}
        for row in injector_rows:
            injector = FuzzLangInjector.from_dict(row)
            injectors[injector.injector_id] = injector.to_dict()
        completed_request_indices: set[int] = set()
        for row in attempts:
            request_index = row.get("request_index")
            if (
                not isinstance(request_index, int)
                or isinstance(request_index, bool)
                or request_index < 0
                or request_index >= len(requests)
            ):
                raise ValueError(
                    "resume checkpoint has an invalid request_index for this shard"
                )
            completed_request_indices.add(request_index)
    else:
        _write_jsonl(requests_path, request_rows)
        _write_jsonl(attempts_path, ())
        _write_jsonl(injectors_path, ())
        attempts = []
        injectors = {}
        completed_request_indices = set()
    excluded_ids = frozenset(excluded_injector_ids)
    if any(not isinstance(injector_id, str) or not injector_id for injector_id in excluded_ids):
        raise ValueError("excluded Injector IDs must be non-empty strings")
    if (
        isinstance(feedback_rounds, bool)
        or not isinstance(feedback_rounds, int)
        or feedback_rounds <= 0
    ):
        raise ValueError("feedback_rounds must be a positive integer")
    if (
        isinstance(request_batch_size, bool)
        or not isinstance(request_batch_size, int)
        or request_batch_size <= 0
    ):
        raise ValueError("request_batch_size must be a positive integer")
    batch_chat = getattr(backend, "chat_batch", None)
    if request_batch_size > 1 and not callable(batch_chat):
        raise ValueError("request_batch_size > 1 requires backend.chat_batch")
    if synthesis_mode not in {"lexical", "fragment"}:
        raise ValueError("synthesis_mode must be 'lexical' or 'fragment'")
    message_builder = (
        build_fragment_synthesis_messages
        if synthesis_mode == "fragment" else build_synthesis_messages
    )
    response_validator = (
        validate_fragment_synthesis_responses
        if synthesis_mode == "fragment" else validate_synthesis_responses
    )
    synthesizer = (
        synthesize_fragment_injectors
        if synthesis_mode == "fragment" else synthesize_injectors
    )
    rejection_counts: Counter[str] = Counter(
        str(row["reason"])
        for row in attempts
        if row.get("status") == "rejected" and isinstance(row.get("reason"), str)
    )
    accepted_candidates = sum(
        row.get("status") == "accepted" for row in attempts
    )
    output_tokens = sum(
        row["output_tokens"] for row in attempts
        if isinstance(row.get("output_tokens"), int)
        and not isinstance(row["output_tokens"], bool)
    )
    # Prompt usage is not archived in an attempt row.  Once resumed, avoid
    # presenting a partial token count as a full campaign measurement.
    prompt_tokens = 0
    prompt_tokens_known = not resume
    token_counter = getattr(backend, "count_prompt_tokens", None)

    feedback_round_requests = len({
        row["request_index"] for row in attempts
        if isinstance(row.get("request_index"), int)
        and isinstance(row.get("feedback_round"), int)
        and row["feedback_round"] > 0
    })
    prefetched_results: dict[int, Any] = {}
    prefetched_prompt_count = 0
    for request_index, request in enumerate(requests):
        if request_batch_size > 1 and request_index % request_batch_size == 0:
            stop = min(request_index + request_batch_size, len(requests))
            batch = [
                (batch_index, requests[batch_index])
                for batch_index in range(request_index, stop)
                if batch_index not in completed_request_indices
            ]
            if not batch:
                continue
            messages_batch = [message_builder(item) for _, item in batch]
            responses_batch = batch_chat(
                messages_batch=messages_batch,
                temperature=temperature,
                max_tokens=max_tokens,
                n=n_candidates,
            )
            if len(responses_batch) != len(batch):
                raise RuntimeError(
                    "chat_batch returned a response group for the wrong number "
                    "of synthesis requests"
                )
            for (batch_index, batch_request), messages, responses in zip(
                batch, messages_batch, responses_batch, strict=True,
            ):
                prompt_tokens = (
                    token_counter(messages) if token_counter is not None else None
                )
                prefetched_results[batch_index] = response_validator(
                    batch_request, responses, prompt_tokens=prompt_tokens,
                )
            prefetched_prompt_count += len(batch)
        if request_index in completed_request_indices:
            continue
        current_request = request
        for feedback_round in range(feedback_rounds):
            if feedback_round == 0 and request_index in prefetched_results:
                result = prefetched_results.pop(request_index)
            else:
                result = synthesizer(
                    current_request,
                    backend,
                    n_candidates=n_candidates,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    prompt_token_counter=token_counter,
                )
            output_tokens += result.usage.output_tokens
            if result.usage.prompt_tokens is None:
                prompt_tokens_known = False
            else:
                prompt_tokens += result.usage.prompt_tokens
            round_rejections: list[str] = []
            round_has_accepted = False
            for attempt in result.attempts:
                injector_id = None
                status = attempt.status
                reason = attempt.reason
                if attempt.injector is not None:
                    candidate_id = attempt.injector.injector_id
                    if candidate_id in excluded_ids:
                        status = "rejected"
                        reason = "duplicate_excluded_injector"
                        rejection_counts[reason] += 1
                    else:
                        accepted_candidates += 1
                        injector_id = candidate_id
                        injectors.setdefault(injector_id, attempt.injector.to_dict())
                        round_has_accepted = True
                elif attempt.reason is not None:
                    rejection_counts[attempt.reason] += 1
                if status == "rejected" and reason is not None:
                    round_rejections.append(reason)
                attempts.append({
                    "request_index": request_index,
                    "diag_name": request.diag_name,
                    "diag_id": request.diag_id,
                    "feedback_round": feedback_round,
                    "candidate_index": attempt.candidate_index,
                    "status": status,
                    "reason": reason,
                    "injector_id": injector_id,
                    "output_tokens": attempt.output_tokens,
                    "raw_text": attempt.raw_text,
                })
            if round_has_accepted or feedback_round + 1 == feedback_rounds:
                break
            feedback_round_requests += 1
            current_request = with_validation_feedback(
                current_request, rejection_reasons=round_rejections,
            )
        # Preserve completed requests even if a later model call fails.  A
        # missing manifest then unambiguously denotes an interrupted campaign.
        _write_jsonl(attempts_path, attempts)
        _write_jsonl(injectors_path, injectors.values())

    _write_jsonl(attempts_path, attempts)
    _write_jsonl(injectors_path, injectors.values())
    candidates = len(attempts)
    manifest = {
        "schema": "fuzzlang.injector-synthesis-campaign",
        "schema_version": 1,
        "model": {
            "name": model_name,
            "revision": model_revision,
            "parameters": "31B",
            "role": "injector_synthesis",
        },
        "paid_api_calls": False,
        "execution": {
            "backend_class": type(backend).__name__,
            "model_path": getattr(backend, "model_path", None),
            "seed": getattr(backend, "seed", None),
        },
        "generation": {
            "candidates_per_request": n_candidates,
            "feedback_rounds": feedback_rounds,
            "request_batch_size": request_batch_size,
            "prefetched_prompt_count": prefetched_prompt_count,
            "temperature": temperature,
            "max_output_tokens": max_tokens,
            "synthesis_mode": synthesis_mode,
            "resumed": resume,
        },
        "counts": {
            "requests": len(requests),
            "candidates": candidates,
            "accepted_candidates": accepted_candidates,
            "unique_injectors": len(injectors),
            "rejected_candidates": candidates - accepted_candidates,
            "excluded_injector_identities": len(excluded_ids),
            "feedback_round_requests": feedback_round_requests,
        },
        "tokens": {
            "prompt": prompt_tokens if prompt_tokens_known else None,
            "output": output_tokens,
        },
        "rejection_reasons": dict(sorted(rejection_counts.items())),
        "files": {
            requests_path.name: _file_metadata(requests_path),
            attempts_path.name: _file_metadata(attempts_path),
            injectors_path.name: _file_metadata(injectors_path),
        },
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Synthesize FuzzLang Injectors offline with the pinned largest Gemma"
        )
    )
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--backend", choices=("vllm", "transformers"), default="vllm",
        help=(
            "vllm uses the local single-node TP=8 server (the production path); "
            "transformers is only for a direct local smoke"
        ),
    )
    parser.add_argument(
        "--base-url", default="http://127.0.0.1:8000/v1",
        help="OpenAI-compatible local vLLM endpoint, used with --backend vllm",
    )
    parser.add_argument(
        "--vllm-concurrency", type=int, default=64,
        help="maximum in-flight HTTP requests to the local TP=8 vLLM server",
    )
    parser.add_argument(
        "--model-path", type=Path, default=DEFAULT_GEMMA_31B_SNAPSHOT,
    )
    parser.add_argument("--candidates", type=int, default=1)
    parser.add_argument(
        "--synthesis-mode", choices=("lexical", "fragment"), default="lexical",
        help="lexical edits or bounded v2 append fragments",
    )
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=1200)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--request-batch-size", type=int, default=64,
        help="distinct diagnostic prompts submitted as one bounded vLLM batch",
    )
    parser.add_argument(
        "--feedback-rounds", type=int, default=2,
        help="retry a target with DSL-validation feedback when its first round has no accepted Injector",
    )
    parser.add_argument(
        "--request-start", type=int, default=0,
        help="zero-based inclusive request index for a bounded retry shard",
    )
    parser.add_argument(
        "--request-stop", type=int,
        help="zero-based exclusive request index for a bounded retry shard",
    )
    parser.add_argument(
        "--require-regression-test-evidence", action="store_true",
        help="only synthesize targets whose prompt carries Clang-test trigger evidence",
    )
    parser.add_argument(
        "--exclude-injectors", type=Path, action="append",
        help=(
            "canonical Injector JSONL whose identities must be rejected from "
            "this synthesis run; repeat for multiple prior batches"
        ),
    )
    parser.add_argument(
        "--resume", action="store_true",
        help=(
            "preserve atomic per-request checkpoints in --output-dir and only "
            "synthesize the unfinished tail of the same bounded shard"
        ),
    )
    return parser


def load_excluded_injector_ids(paths: Sequence[Path] | None) -> tuple[str, ...]:
    """Read canonical prior Injector artifacts into a deterministic ID set."""
    ids: set[str] = set()
    for path in paths or ():
        for line_number, line in enumerate(path.read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                injector = FuzzLangInjector.from_json(line)
            except ValueError as error:
                raise ValueError(
                    f"{path}:{line_number}: invalid excluded Injector: {error}"
                ) from error
            ids.add(injector.injector_id)
    return tuple(sorted(ids))


def main() -> None:
    args = _parser().parse_args()
    require_gemma_31b(args.model_path)
    if args.model_path.resolve() != DEFAULT_GEMMA_31B_SNAPSHOT.resolve():
        _parser().error(
            "--model-path must be the pinned local Gemma-4-31B-it snapshot "
            f"{DEFAULT_GEMMA_31B_SNAPSHOT}"
        )
    all_requests = load_request_file(args.requests)
    if args.require_regression_test_evidence:
        all_requests = require_regression_test_evidence(all_requests)
    try:
        requests = select_request_range(
            all_requests, start=args.request_start, stop=args.request_stop,
        )
        excluded_ids = load_excluded_injector_ids(args.exclude_injectors)
    except ValueError as error:
        _parser().error(str(error))
    if args.backend == "vllm":
        backend: ChatBackend = VLLMChatBackend(
            "gemma-4-31B-it",
            base_url=args.base_url,
            timeout_s=600.0,
            max_concurrency=args.vllm_concurrency,
        )
    else:
        backend = LocalGemma31BBackend(args.model_path, seed=args.seed)
    manifest = run_synthesis_campaign(
        requests,
        backend,
        output_dir=args.output_dir,
        model_name=DEFAULT_GEMMA_31B_MODEL,
        model_revision=DEFAULT_GEMMA_31B_REVISION,
        n_candidates=args.candidates,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        feedback_rounds=args.feedback_rounds,
        request_batch_size=args.request_batch_size,
        synthesis_mode=args.synthesis_mode,
        excluded_injector_ids=excluded_ids,
        resume=args.resume,
    )
    print(json.dumps(manifest["counts"], sort_keys=True))


if __name__ == "__main__":
    main()
