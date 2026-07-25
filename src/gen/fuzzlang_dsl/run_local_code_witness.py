#!/usr/bin/env python3
"""Use local Gemma to propose compiler-validated seed witness edits."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from foundation.record import Origin, Provenance, Record, Split
from foundation.verifier import FuzzlangClangVerifier
from gen.fuzzlang_dsl.breadth_targets import (
    supports_ordinary_cpp_diagnostic_name,
)
from gen.fuzzlang_dsl.code_witness import (
    CodeWitnessRequest, apply_code_witness_patch, build_code_witness_messages,
    build_code_witness_retry_messages, parse_code_witness_patch,
)
from gen.fuzzlang_dsl.context_variants import (
    DEFAULT_RECIPE_CONTEXT_TOKENS,
    extract_contextual_injectors,
    load_excluded_injector_ids,
)
from gen.fuzzlang_dsl.injector import FuzzLangInjector, apply_injector
from gen.fuzzlang_dsl.local_gemma import (
    DEFAULT_GEMMA_31B_MODEL, DEFAULT_GEMMA_31B_REVISION,
    DEFAULT_GEMMA_31B_SNAPSHOT, LocalGemma31BBackend,
)


def _load(path: Path) -> list[CodeWitnessRequest]:
    return [CodeWitnessRequest.from_dict(json.loads(line)) for line in path.read_text().splitlines() if line.strip()]


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def _write_checkpoint(
    output_dir: Path,
    *,
    attempts: list[dict],
    records: list[dict],
    undistillable_records: list[dict],
    injectors: dict[str, dict],
) -> None:
    """Persist all completed request results before issuing another model call."""
    _write(output_dir / "attempts.jsonl", attempts)
    _write(output_dir / "records.jsonl", records)
    _write(
        output_dir / "undistillable_records.jsonl",
        undistillable_records,
    )
    _write(output_dir / "injectors.jsonl", list(injectors.values()))


def _candidate_round_counts(
    candidates: int, feedback_rounds: int,
) -> tuple[int, ...]:
    """Evenly partition a fixed model budget into adaptive rounds."""
    if candidates <= 0 or feedback_rounds <= 0:
        raise ValueError("candidate and feedback-round bounds must be positive")
    rounds = min(candidates, feedback_rounds)
    base, remainder = divmod(candidates, rounds)
    return tuple(base + (index < remainder) for index in range(rounds))


def _select_exact_replay(
    *,
    corrected_src: str,
    candidates: tuple[FuzzLangInjector, ...],
    diag_name: str,
    diag_id: int,
    compile_cmd: list[str],
    logical_path: str,
    verifier: FuzzlangClangVerifier,
) -> tuple[FuzzLangInjector, str, object] | None:
    """Return one Injector whose own replay reproduces the typed target.

    A model patch is only a witness.  Core FuzzLang data is admitted only
    after the emitted DSL artifact itself is applied to the clean source and
    the compiler reports the requested diagnostic name *and* numeric ID.
    """
    for injector in candidates:
        for application in apply_injector(
            corrected_src, injector, max_candidates=1,
        ):
            replayed = verifier.verify(
                application.src, compile_cmd, logical_path=logical_path,
            )
            if (
                not replayed.ok
                and replayed.diag is not None
                and replayed.diag.diag_name == diag_name
                and replayed.diag.diag_id == diag_id
            ):
                return injector, application.src, replayed.diag
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--clang-bin", required=True)
    parser.add_argument("--clang-c-bin", required=True)
    parser.add_argument("--diagtool-bin", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--exclude-injectors", type=Path, action="append", default=[],
        help="canonical Injector JSONL whose identities must not be re-emitted",
    )
    parser.add_argument("--candidates", type=int, default=4)
    parser.add_argument(
        "--feedback-rounds", type=int, default=2,
        help="adaptive model rounds sharing the fixed candidate budget",
    )
    parser.add_argument("--temperature", type=float, default=0.5)
    parser.add_argument("--max-tokens", type=int, default=400)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--admit-observed-errors", action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "when a candidate misses its requested target, retain its actual "
            "primary error only if it can itself be distilled and exactly replayed"
        ),
    )
    parser.add_argument(
        "--recipe-context-tokens", type=int, action="append", default=None,
        help="repeatable lexical-context level; defaults to 1, 2, and 3",
    )
    args = parser.parse_args()
    if (
        args.candidates <= 0
        or args.feedback_rounds <= 0
        or args.max_tokens <= 0
        or args.timeout <= 0
    ):
        parser.error("candidate, token, and timeout bounds must be positive")
    context_tokens = tuple(
        args.recipe_context_tokens
        if args.recipe_context_tokens is not None
        else DEFAULT_RECIPE_CONTEXT_TOKENS
    )
    if any(level < 0 for level in context_tokens):
        parser.error("recipe context levels must be non-negative")
    requests = _load(args.requests)
    excluded_injector_ids = frozenset(load_excluded_injector_ids(args.exclude_injectors))
    backend = LocalGemma31BBackend(DEFAULT_GEMMA_31B_SNAPSHOT, seed=args.seed)
    verifier = FuzzlangClangVerifier(args.clang_bin, args.diagtool_bin, args.timeout, clang_c_bin=args.clang_c_bin)
    attempts: list[dict] = []
    records: list[dict] = []
    undistillable_records: list[dict] = []
    injectors: dict[str, dict] = {}
    duplicate_existing_injector_candidates = 0
    feedback_round_requests = 0
    _write_checkpoint(
        args.output_dir,
        attempts=attempts,
        records=records,
        undistillable_records=undistillable_records,
        injectors=injectors,
    )
    for request_index, request in enumerate(requests):
        if not supports_ordinary_cpp_diagnostic_name(request.diag_name):
            attempts.append({
                "request_index": request_index,
                "diag_name": request.diag_name,
                "status": "unsupported_ordinary_cpp_mode",
            })
            _write_checkpoint(
                args.output_dir,
                attempts=attempts,
                records=records,
                undistillable_records=undistillable_records,
                injectors=injectors,
            )
            continue
        baseline = verifier.verify(request.corrected_src, list(request.compile_cmd), logical_path=request.source_path)
        if not baseline.ok:
            attempts.append({"request_index": request_index, "diag_name": request.diag_name, "status": "baseline_not_clean"})
            _write_checkpoint(
                args.output_dir,
                attempts=attempts,
                records=records,
                undistillable_records=undistillable_records,
                injectors=injectors,
            )
            continue
        messages = build_code_witness_messages(request)
        rejection_reasons: set[str] = set()
        observed_diagnostics: set[str] = set()
        accepted = False
        candidate_index = 0
        for round_index, candidate_count in enumerate(
            _candidate_round_counts(args.candidates, args.feedback_rounds)
        ):
            if accepted:
                continue
            if round_index > 0:
                feedback_round_requests += 1
                messages = build_code_witness_retry_messages(
                    request,
                    rejection_reasons=tuple(rejection_reasons),
                    observed_diagnostics=tuple(observed_diagnostics),
                )
            responses = backend.chat(
                messages=messages,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                n=candidate_count,
            )
            for response in responses:
                patch, reason = parse_code_witness_patch(response.text, request)
                row = {
                    "request_index": request_index,
                    "diag_name": request.diag_name,
                    "candidate_index": candidate_index,
                    "candidate_round": round_index + 1,
                    "output_tokens": response.output_tokens,
                    "reason": reason,
                }
                candidate_index += 1
                if patch is None:
                    row["status"] = "rejected"
                    attempts.append(row)
                    if reason:
                        rejection_reasons.add(reason)
                    continue
                erroneous = apply_code_witness_patch(request, patch)
                verified = verifier.verify(
                    erroneous,
                    list(request.compile_cmd),
                    logical_path=request.source_path,
                )
                if verified.ok or verified.diag is None:
                    row["status"] = "rejected"
                    row["reason"] = "candidate_clean_or_wrong_primary"
                    row["observed_diag"] = (
                        verified.diag.diag_name if verified.diag else None
                    )
                    attempts.append(row)
                    rejection_reasons.add(row["reason"])
                    if verified.diag is not None:
                        observed_diagnostics.add(verified.diag.diag_name)
                    continue
                target_diag_name = request.diag_name
                opportunistic = False
                if verified.diag.diag_name != request.diag_name:
                    observed_diagnostics.add(verified.diag.diag_name)
                    if not args.admit_observed_errors:
                        row["status"] = "rejected"
                        row["reason"] = "candidate_clean_or_wrong_primary"
                        row["observed_diag"] = verified.diag.diag_name
                        attempts.append(row)
                        rejection_reasons.add(row["reason"])
                        continue
                    target_diag_name = verified.diag.diag_name
                    opportunistic = True
                record_id = "code-witness-" + hashlib.sha256(
                    (request.source_id + "\0" + erroneous).encode()
                ).hexdigest()[:24]
                record = Record(
                    record_id=record_id,
                    erroneous_src=erroneous,
                    corrected_src=request.corrected_src,
                    diagnostics=(verified.diag,),
                    split=Split.TRAIN,
                    language=request.language,
                    provenance=Provenance(
                        origin=Origin.MUTATE,
                        source=request.source_id,
                        detail={
                            "strategy": "gemma_code_witness_bootstrap",
                            "project": request.project,
                            "source_path": request.source_path,
                            "compile_cmd": list(request.compile_cmd),
                            "target_diag": target_diag_name,
                            "primary_matches_target": True,
                            "opportunistic_observed_diagnostic": opportunistic,
                        },
                    ),
                )
                candidate_injectors: dict[str, FuzzLangInjector] = {}
                for preserve_spelling in (False, True):
                    for injector in extract_contextual_injectors(
                        record,
                        diag_id=verified.diag.diag_id,
                        context_tokens=context_tokens,
                        preserve_inserted_identifier_spellings=preserve_spelling,
                    ):
                        candidate_injectors[injector.injector_id] = injector
                selected = _select_exact_replay(
                    corrected_src=request.corrected_src,
                    candidates=tuple(candidate_injectors.values()),
                    diag_name=target_diag_name,
                    diag_id=verified.diag.diag_id,
                    compile_cmd=list(request.compile_cmd),
                    logical_path=request.source_path,
                    verifier=verifier,
                )
                if selected is None:
                    row["status"] = "exact_target_not_distillable"
                    row["reason"] = "no_exact_replayable_injector"
                    row["recovery_record_id"] = record.record_id
                    attempts.append(row)
                    undistillable_records.append(record.to_dict())
                    rejection_reasons.add(row["reason"])
                    continue
                injector, replayed_src, replayed_diag = selected
                replay_record_id = "code-witness-injector-" + hashlib.sha256(
                    (request.source_id + "\0" + injector.injector_id + "\0" + replayed_src).encode()
                ).hexdigest()[:24]
                replay_record = Record(
                    record_id=replay_record_id,
                    erroneous_src=replayed_src,
                    corrected_src=request.corrected_src,
                    diagnostics=(replayed_diag,),
                    split=Split.TRAIN,
                    language=request.language,
                    provenance=Provenance(
                        origin=Origin.MUTATE,
                        source=request.source_id,
                        detail={
                            **record.provenance.detail,
                            "strategy": "gemma_code_witness_injector_replay",
                            "injector_id": injector.injector_id,
                            "injector_replay_exact": True,
                        },
                    ),
                )
                if injector.injector_id in excluded_injector_ids:
                    row["injector_status"] = "duplicate_excluded_injector"
                    duplicate_existing_injector_candidates += 1
                else:
                    injectors[injector.injector_id] = injector.to_dict()
                row["status"] = (
                    "exact_observed_diagnostic"
                    if opportunistic else "exact_target"
                )
                row["record_id"] = replay_record.record_id
                row["injector_id"] = injector.injector_id
                if opportunistic:
                    row["observed_diag"] = target_diag_name
                attempts.append(row)
                records.append(replay_record.to_dict())
                accepted = True
                break
        _write_checkpoint(
            args.output_dir,
            attempts=attempts,
            records=records,
            undistillable_records=undistillable_records,
            injectors=injectors,
        )
    _write_checkpoint(
        args.output_dir,
        attempts=attempts,
        records=records,
        undistillable_records=undistillable_records,
        injectors=injectors,
    )
    manifest = {"schema": "fuzzlang.code_witness_bootstrap", "model": {"name": DEFAULT_GEMMA_31B_MODEL, "revision": DEFAULT_GEMMA_31B_REVISION, "parameters": "31B"}, "paid_api_calls": False, "recipe_context_tokens": list(context_tokens), "counts": {"requests": len(requests), "attempts": len(attempts), "records": len(records), "undistillable_records": len(undistillable_records), "portable_injectors": len(injectors), "excluded_injector_identities": len(excluded_injector_ids), "duplicate_existing_injector_candidates": duplicate_existing_injector_candidates, "feedback_round_requests": feedback_round_requests}}
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")
    print(json.dumps(manifest["counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
