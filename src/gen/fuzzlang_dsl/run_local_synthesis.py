#!/usr/bin/env python3
"""Synthesize and archive FuzzLang Injectors with local Gemma-4-31B-it."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence, TypeVar

from gen.fuzzlang_dsl.local_gemma import (
    DEFAULT_GEMMA_31B_MODEL,
    DEFAULT_GEMMA_31B_REVISION,
    DEFAULT_GEMMA_31B_SNAPSHOT,
    LocalGemma31BBackend,
    load_request_file,
    require_gemma_31b,
)
from gen.fuzzlang_dsl.synthesis import (
    SynthesisRequest,
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
    rejection_counts: Counter[str] = Counter()
    accepted_candidates = 0
    output_tokens = 0
    prompt_tokens = 0
    prompt_tokens_known = True
    token_counter = getattr(backend, "count_prompt_tokens", None)

    for request_index, request in enumerate(requests):
        result = synthesize_injectors(
            request,
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
        for attempt in result.attempts:
            injector_id = None
            if attempt.injector is not None:
                accepted_candidates += 1
                injector_id = attempt.injector.injector_id
                injectors.setdefault(injector_id, attempt.injector.to_dict())
            elif attempt.reason is not None:
                rejection_counts[attempt.reason] += 1
            attempts.append({
                "request_index": request_index,
                "diag_name": request.diag_name,
                "diag_id": request.diag_id,
                "candidate_index": attempt.candidate_index,
                "status": attempt.status,
                "reason": attempt.reason,
                "injector_id": injector_id,
                "output_tokens": attempt.output_tokens,
                "raw_text": attempt.raw_text,
            })
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
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        },
        "counts": {
            "requests": len(requests),
            "candidates": candidates,
            "accepted_candidates": accepted_candidates,
            "unique_injectors": len(injectors),
            "rejected_candidates": candidates - accepted_candidates,
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
        "--request-start", type=int, default=0,
        help="zero-based inclusive request index for a bounded retry shard",
    )
    parser.add_argument(
        "--request-stop", type=int,
        help="zero-based exclusive request index for a bounded retry shard",
    )
    return parser


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
    )
    print(json.dumps(manifest["counts"], sort_keys=True))


if __name__ == "__main__":
    main()
