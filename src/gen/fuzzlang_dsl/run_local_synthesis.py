#!/usr/bin/env python3
"""Synthesize and archive FuzzLang Injectors with local Gemma-4-31B-it."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Sequence, TypeVar

from gen.fuzzlang_dsl.injector import FuzzLangInjector
from gen.fuzzlang_dsl.local_gemma import (
    DEFAULT_GEMMA_31B_MODEL,
    DEFAULT_GEMMA_31B_REVISION,
    DEFAULT_GEMMA_31B_SNAPSHOT,
    LocalGemma31BBackend,
    load_request_file,
    require_gemma_31b,
)
from gen.fuzzlang_dsl.synthesis import (
    DiagnosticEvidence, SynthesisRequest,
    synthesize_injectors,
)
from repair.agent.chat_backend import ChatBackend


_RequestT = TypeVar("_RequestT")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    )


def _write_jsonl(path: Path, values: Iterable[dict[str, Any]]) -> None:
    path.write_text("".join(_canonical_json(value) + "\n" for value in values))


def _file_metadata(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "rows": sum(1 for line in payload.splitlines() if line.strip()),
    }


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
    excluded_injector_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """Run bounded synthesis and preserve every raw/validated outcome."""
    require_gemma_31b(model_name)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    requests_path = output_dir / "requests.jsonl"
    attempts_path = output_dir / "attempts.jsonl"
    injectors_path = output_dir / "injectors.jsonl"
    _write_jsonl(requests_path, (_request_dict(item) for item in requests))
    _write_jsonl(attempts_path, ())
    _write_jsonl(injectors_path, ())
    attempts: list[dict[str, Any]] = []
    injectors: dict[str, dict[str, Any]] = {}
    excluded_ids = frozenset(excluded_injector_ids)
    if any(not isinstance(injector_id, str) or not injector_id for injector_id in excluded_ids):
        raise ValueError("excluded Injector IDs must be non-empty strings")
    if (
        isinstance(feedback_rounds, bool)
        or not isinstance(feedback_rounds, int)
        or feedback_rounds <= 0
    ):
        raise ValueError("feedback_rounds must be a positive integer")
    rejection_counts: Counter[str] = Counter()
    accepted_candidates = 0
    output_tokens = 0
    prompt_tokens = 0
    prompt_tokens_known = True
    token_counter = getattr(backend, "count_prompt_tokens", None)

    feedback_round_requests = 0
    for request_index, request in enumerate(requests):
        current_request = request
        for feedback_round in range(feedback_rounds):
            result = synthesize_injectors(
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
            "temperature": temperature,
            "max_output_tokens": max_tokens,
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
        "--model-path", type=Path, default=DEFAULT_GEMMA_31B_SNAPSHOT,
    )
    parser.add_argument("--candidates", type=int, default=1)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=1200)
    parser.add_argument("--seed", type=int, default=0)
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
        "--exclude-injectors", type=Path, action="append",
        help=(
            "canonical Injector JSONL whose identities must be rejected from "
            "this synthesis run; repeat for multiple prior batches"
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
    try:
        requests = select_request_range(
            all_requests, start=args.request_start, stop=args.request_stop,
        )
        excluded_ids = load_excluded_injector_ids(args.exclude_injectors)
    except ValueError as error:
        _parser().error(str(error))
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
        excluded_injector_ids=excluded_ids,
    )
    print(json.dumps(manifest["counts"], sort_keys=True))


if __name__ == "__main__":
    main()
