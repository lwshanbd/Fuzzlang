#!/usr/bin/env python3
"""Have local Gemma author DSL Injectors and exact-replay them on seed TUs."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Iterable, Sequence

from foundation.verifier import FuzzlangClangVerifier
from gen.fuzzlang_dsl.code_witness import (
    CodeWitnessRequest, build_direct_injector_requests,
)
from gen.fuzzlang_dsl.direct_source import replay_direct_injector_on_source
from gen.fuzzlang_dsl.injector import FuzzLangInjector
from gen.fuzzlang_dsl.local_gemma import (
    DEFAULT_GEMMA_31B_MODEL, DEFAULT_GEMMA_31B_REVISION,
    DEFAULT_GEMMA_31B_SNAPSHOT, LocalGemma31BBackend,
)
from gen.fuzzlang_dsl.synthesis import SynthesisRequest, synthesize_injectors


def _write(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
    ))


def _load(path: Path) -> tuple[CodeWitnessRequest, ...]:
    return tuple(
        CodeWitnessRequest.from_dict(json.loads(line))
        for line in path.read_text().splitlines() if line.strip()
    )


def _source_groups(
    witnesses: Sequence[CodeWitnessRequest], *, snippets_per_target: int,
) -> dict[str, tuple[CodeWitnessRequest, ...]]:
    grouped: dict[str, list[CodeWitnessRequest]] = {}
    for witness in witnesses:
        grouped.setdefault(witness.diag_name, []).append(witness)
    selected: dict[str, tuple[CodeWitnessRequest, ...]] = {}
    for diag_name, candidates in grouped.items():
        unique: list[CodeWitnessRequest] = []
        seen_sources: set[str] = set()
        for witness in sorted(candidates, key=lambda item: item.source_id):
            if witness.source_id not in seen_sources:
                seen_sources.add(witness.source_id)
                unique.append(witness)
            if len(unique) == snippets_per_target:
                break
        if len(unique) == snippets_per_target:
            selected[diag_name] = tuple(unique)
    return selected


def run_direct_source_campaign(
    witnesses: Sequence[CodeWitnessRequest], backend, verifier, *,
    output_dir: Path, snippets_per_target: int = 2, candidates: int = 2,
    temperature: float = 0.2, max_tokens: int = 1200,
    request_start: int = 0, request_stop: int | None = None,
    excluded_injector_ids: Iterable[str] = (),
) -> dict:
    """Synthesize direct DSL artifacts, then admit only exact seed replays."""
    groups = _source_groups(witnesses, snippets_per_target=snippets_per_target)
    requests = build_direct_injector_requests(
        witnesses, snippets_per_target=snippets_per_target,
    )
    if request_start < 0 or request_start > len(requests):
        raise ValueError("request_start must fall within the request range")
    resolved_stop = len(requests) if request_stop is None else request_stop
    if resolved_stop < request_start or resolved_stop > len(requests):
        raise ValueError("request_stop must fall within the request range")
    selected_requests = requests[request_start:resolved_stop]
    excluded = frozenset(excluded_injector_ids)
    if any(not isinstance(item, str) or not item for item in excluded):
        raise ValueError("excluded Injector IDs must be non-empty strings")

    output_dir = Path(output_dir)
    attempts: list[dict] = []
    injectors: dict[str, dict] = {}
    records: list[dict] = []
    rejection_counts: Counter[str] = Counter()
    output_tokens = 0
    for request_index, request in enumerate(selected_requests):
        result = synthesize_injectors(
            request, backend, n_candidates=candidates,
            temperature=temperature, max_tokens=max_tokens,
            prompt_token_counter=getattr(backend, "count_prompt_tokens", None),
        )
        output_tokens += result.usage.output_tokens
        exact = False
        for attempt in result.attempts:
            row = {
                "request_index": request_start + request_index,
                "diag_name": request.diag_name,
                "diag_id": request.diag_id,
                "candidate_index": attempt.candidate_index,
                "status": attempt.status,
                "reason": attempt.reason,
                "output_tokens": attempt.output_tokens,
                "raw_text": attempt.raw_text,
            }
            injector = attempt.injector
            if injector is None:
                if attempt.reason:
                    rejection_counts[attempt.reason] += 1
                attempts.append(row)
                continue
            if injector.injector_id in excluded:
                row.update(status="rejected", reason="duplicate_excluded_injector")
                rejection_counts[row["reason"]] += 1
                attempts.append(row)
                continue
            record = None
            for witness in groups[request.diag_name]:
                record = replay_direct_injector_on_source(
                    injector, witness, verifier,
                )
                if record is not None:
                    break
            if record is None:
                row.update(status="rejected", reason="no_exact_seed_replay")
                rejection_counts[row["reason"]] += 1
                attempts.append(row)
                continue
            injectors[injector.injector_id] = injector.to_dict()
            records.append(record.to_dict())
            row.update(status="exact_seed_replay", injector_id=injector.injector_id,
                       record_id=record.record_id)
            attempts.append(row)
            exact = True
            break
        _write(output_dir / "attempts.jsonl", attempts)
        _write(output_dir / "injectors.jsonl", injectors.values())
        _write(output_dir / "records.jsonl", records)
        # A successful target has a useful Injector already; reserve the next
        # target for coverage breadth rather than spending more calls here.
        if exact:
            continue
    manifest = {
        "schema": "fuzzlang.direct_source_injector_campaign",
        "schema_version": 1,
        "model": {"name": DEFAULT_GEMMA_31B_MODEL,
                  "revision": DEFAULT_GEMMA_31B_REVISION, "parameters": "31B"},
        "paid_api_calls": False,
        "acceptance_rule": "exact typed seed replay before cross-source replay",
        "counts": {"requests": len(selected_requests), "attempts": len(attempts),
                   "unique_injectors": len(injectors), "seed_records": len(records)},
        "tokens": {"output": output_tokens},
        "rejection_reasons": dict(sorted(rejection_counts.items())),
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--witness-requests", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--clang-bin", required=True)
    parser.add_argument("--clang-c-bin", required=True)
    parser.add_argument("--diagtool-bin", required=True)
    parser.add_argument("--snippets-per-target", type=int, default=2)
    parser.add_argument("--candidates", type=int, default=2)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=1200)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--request-start", type=int, default=0)
    parser.add_argument("--request-stop", type=int)
    args = parser.parse_args()
    if not 2 <= args.snippets_per_target <= 5:
        parser.error("--snippets-per-target must be between 2 and 5")
    if args.candidates <= 0 or args.max_tokens <= 0 or args.timeout <= 0:
        parser.error("candidate, token, and timeout bounds must be positive")
    backend = LocalGemma31BBackend(DEFAULT_GEMMA_31B_SNAPSHOT)
    verifier = FuzzlangClangVerifier(
        args.clang_bin, args.diagtool_bin, args.timeout,
        clang_c_bin=args.clang_c_bin,
    )
    manifest = run_direct_source_campaign(
        _load(args.witness_requests), backend, verifier, output_dir=args.output_dir,
        snippets_per_target=args.snippets_per_target, candidates=args.candidates,
        temperature=args.temperature, max_tokens=args.max_tokens,
        request_start=args.request_start, request_stop=args.request_stop,
    )
    print(json.dumps(manifest["counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
