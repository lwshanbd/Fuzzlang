#!/usr/bin/env python3
"""Use local Gemma to propose compiler-validated seed witness edits."""
from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from foundation.diagnostics.catalog import load_catalog
from foundation.record import Origin, Provenance, Record, Split
from foundation.verifier import FuzzlangClangVerifier
from gen.fuzzlang_dsl.breadth_targets import (
    supports_default_diagnostic_name,
)
from gen.fuzzlang_dsl.code_witness import (
    CodeWitnessRequest, apply_code_witness_patch, build_code_witness_messages,
    apply_code_append_fragment, build_code_append_messages,
    build_code_append_retry_messages, build_code_witness_retry_messages,
    parse_code_append_fragment, parse_code_witness_patch,
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
from gen.fuzzlang_dsl.regression_evidence import (
    has_regression_trigger_evidence, regression_evidence_for,
)
from repair.agent.chat_backend import ChatBackend, VLLMChatBackend


DEFAULT_REGRESSION_TEST_ROOT = Path("external/llvm-project/clang/test")


def _load(path: Path) -> list[CodeWitnessRequest]:
    return [CodeWitnessRequest.from_dict(json.loads(line)) for line in path.read_text().splitlines() if line.strip()]


def _supports_request_compile_mode(
    request: CodeWitnessRequest, *, allow_preprocessor_directives: bool = False,
) -> bool:
    """Apply the breadth filter using the request's verified language mode.

    ``CodeWitnessRequest`` deliberately stores the complete verified compiler
    command rather than a duplicate mode schema.  Recover just ``-std=`` here
    so C11/C23 and C++20/C++23 witnesses are not incorrectly screened as the
    default C++17 campaign before compiler verification.
    """
    source_language = {
        "objective-c": "c",
        "objective-c++": "c++",
    }.get(request.language, request.language)
    cpp_standard = "c++17"
    c_standard = "c17"
    feature_modes = {"ordinary"}
    command = request.compile_cmd
    for argument in command:
        if not argument.startswith("-std="):
            continue
        standard = argument.removeprefix("-std=")
        if standard in {"c++17", "c++20", "c++23", "c++2c"}:
            cpp_standard = standard
        elif standard in {"c99", "c11", "c17", "c23"}:
            c_standard = standard
    if "-fopenmp" in command:
        feature_modes.add("openmp")
    if "-fopenacc" in command:
        feature_modes.add("openacc")
    if "-fblocks" in command:
        feature_modes.add("blocks")
    if any(argument in {"-fmodules", "-fcxx-modules"}
           or argument.startswith("-fmodule-file") for argument in command):
        feature_modes.add("modules")
    if any(
        argument.startswith("--target=")
        or argument in {"-target", "-triple"}
        for argument in command
    ):
        feature_modes.add("target")
    if any(
        argument in {
            "-fdefer-ts", "-fms-extensions", "-fno-gnu-inline-asm", "-fsycl",
            "-fsycl-is-device",
        }
        for argument in command
    ):
        feature_modes.add("profile")
    # A preprocessor witness needs no hidden driver flag, but it must be an
    # explicitly labelled request and the caller must opt into bounded
    # directive fragments.  Do not use this escape hatch for other special
    # compilation modes, which require their concrete clean-gated flags.
    if (
        allow_preprocessor_directives
        and request.feature_mode == "preprocessor"
    ):
        feature_modes.add("preprocessor")
    for index, argument in enumerate(command[:-1]):
        if argument == "-x" and command[index + 1].startswith("objective-"):
            feature_modes.add("objc")
    return any(
        supports_default_diagnostic_name(
            request.diag_name,
            language=source_language,
            cpp_standard=cpp_standard,
            c_standard=c_standard,
            feature_mode=feature_mode,
        )
        for feature_mode in feature_modes
    )


def load_excluded_injector_target_names(paths: list[Path]) -> frozenset[str]:
    """Load previously emitted Injector targets to preserve breadth budget.

    The model often produces a valid but high-frequency diagnostic while aiming
    for a harder uncovered target.  Those candidates are useful only when the
    observed type is new; otherwise they consume a request that could continue
    toward the requested gap.
    """
    names: set[str] = set()
    for path in paths:
        for line in path.read_text().splitlines():
            if line.strip():
                names.add(FuzzLangInjector.from_dict(json.loads(line)).target_diag)
    return frozenset(names)


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        for row in rows
    )
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(payload)
    temporary.replace(path)


def _write_checkpoint(
    output_dir: Path,
    *,
    attempts: list[dict],
    records: list[dict],
    undistillable_records: list[dict],
    injectors: dict[str, dict],
) -> None:
    """Persist result payloads before atomically advancing request progress.

    ``attempts`` determines the resume cursor.  It must be the last file
    replaced: a scheduler interruption can then replay at most one completed
    request, rather than skip a request whose Injector or Record has not yet
    reached durable storage.
    """
    _write(output_dir / "records.jsonl", records)
    _write(
        output_dir / "undistillable_records.jsonl",
        undistillable_records,
    )
    _write(output_dir / "injectors.jsonl", list(injectors.values()))
    _write(output_dir / "attempts.jsonl", attempts)


def _load_resume_checkpoint(
    output_dir: Path,
) -> tuple[list[dict], list[dict], list[dict], dict[str, dict], set[int]]:
    """Load a request-boundary checkpoint from a timed generation job."""
    def load_rows(name: str) -> list[dict]:
        path = output_dir / name
        if not path.exists():
            return []
        rows = [json.loads(line) for line in path.read_text().splitlines() if line]
        if any(not isinstance(row, dict) for row in rows):
            raise ValueError(f"resume checkpoint {path} contains a non-object row")
        return rows

    attempts = load_rows("attempts.jsonl")
    records = load_rows("records.jsonl")
    undistillable_records = load_rows("undistillable_records.jsonl")
    injector_rows = load_rows("injectors.jsonl")
    injectors = {
        row["injector_id"]: row
        for row in injector_rows
        if isinstance(row.get("injector_id"), str) and row["injector_id"]
    }
    if len(injectors) != len(injector_rows):
        raise ValueError("resume checkpoint Injector row lacks injector_id")
    completed_indices = {
        row["request_index"]
        for row in attempts
        if isinstance(row.get("request_index"), int)
        and not isinstance(row["request_index"], bool)
    }
    return attempts, records, undistillable_records, injectors, completed_indices


def _accepted_target_names(injectors: dict[str, dict]) -> set[str]:
    """Return campaign targets already backed by an exact replayable Injector."""
    return {
        FuzzLangInjector.from_dict(row).target_diag
        for row in injectors.values()
    }


def _candidate_round_counts(
    candidates: int, feedback_rounds: int,
) -> tuple[int, ...]:
    """Evenly partition a fixed model budget into adaptive rounds."""
    if candidates <= 0 or feedback_rounds <= 0:
        raise ValueError("candidate and feedback-round bounds must be positive")
    rounds = min(candidates, feedback_rounds)
    base, remainder = divmod(candidates, rounds)
    return tuple(base + (index < remainder) for index in range(rounds))


def _verify_candidate_sources(
    verifier: object,
    sources: list[str],
    *,
    compile_cmd: list[str],
    logical_path: str,
    workers: int,
) -> list[object]:
    """Verify independent candidate sources concurrently in stable order."""
    if workers <= 0:
        raise ValueError("verification workers must be positive")

    def verify(source: str) -> object:
        return verifier.verify(source, compile_cmd, logical_path=logical_path)

    if workers == 1 or len(sources) < 2:
        return [verify(source) for source in sources]
    with ThreadPoolExecutor(max_workers=min(workers, len(sources))) as pool:
        return list(pool.map(verify, sources))


def _known_covered_only_round_streak(
    previous_streak: int, rejection_reasons: set[str],
) -> int:
    """Count consecutive rounds that can only reproduce covered diagnostics.

    An opportunistic error is valuable only the first time it expands coverage.
    If all candidates in a round merely reproduce an already-covered observed
    type, model feedback can help once; repeating that exact dead end again is
    a poor use of the fixed local-model budget.
    """
    if rejection_reasons == {"observed_diagnostic_already_covered"}:
        return previous_streak + 1
    return 0


def is_catalog_error_diagnostic_name(
    diagnostic_name: str, catalog_error_names: frozenset[str],
) -> bool:
    """Whether an opportunistically observed diagnostic can expand coverage.

    The coverage denominator is the pinned TableGen error catalog.  Typed
    compiler output also contains warnings, notes, and implementation-only
    diagnostics; retaining those as observed outcomes creates seemingly valid
    records that the strict audit must later discard.  Filter them at the
    expensive model-generation stage instead.
    """
    return diagnostic_name in catalog_error_names


def with_regression_trigger_evidence(
    request: CodeWitnessRequest,
    test_root: Path,
) -> CodeWitnessRequest:
    """Attach optional compiler-test evidence without changing dataset source.

    The returned request retains its original production ``corrected_src``,
    source identity, and compile command.  The test snippet is only prompt
    context used to infer a rare diagnostic's trigger condition.
    """
    # The large campaign request builder can already carry a bounded Clang
    # regression-test window recovered in an earlier audit.  Do not launch one
    # ripgrep scan per target merely to rediscover the same prompt-only text.
    # This matters for 100--500-target single-node batches: evidence lookup is
    # CPU/metadata bound and otherwise delays the GPU after it is healthy.
    if has_regression_trigger_evidence(request.emission_evidence):
        return request
    regression = regression_evidence_for(request.diag_message, test_root)
    if regression is None:
        return request
    evidence = (
        regression if request.emission_evidence is None
        else request.emission_evidence + "\n\n" + regression
    )
    return replace(request, emission_evidence=evidence)


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
    parser.add_argument(
        "--backend", choices=("local", "vllm"), default="local",
        help="local Transformers backend or the one-node TP=8 vLLM server",
    )
    parser.add_argument(
        "--base-url", default="http://127.0.0.1:8000/v1",
        help="OpenAI-compatible URL when --backend=vllm",
    )
    parser.add_argument(
        "--vllm-concurrency", type=int, default=64,
        help="maximum concurrent requests when --backend=vllm",
    )
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
    parser.add_argument(
        "--request-batch-size", type=int, default=1,
        help=(
            "number of distinct diagnostic prompts generated together; wide "
            "mode requires one feedback round and preserves compiler gating"
        ),
    )
    parser.add_argument("--temperature", type=float, default=0.5)
    parser.add_argument("--max-tokens", type=int, default=400)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument(
        "--verification-workers", type=int, default=16,
        help="parallel Clang verifications per model candidate round",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="continue from the request-boundary checkpoint in --output-dir",
    )
    parser.add_argument(
        "--witness-mode", choices=("replace", "append"), default="replace",
        help=(
            "replace a bounded real-code substring, or append a bounded "
            "declaration witness before extracting the replayable Injector"
        ),
    )
    parser.add_argument(
        "--allow-preprocessor-directives", action="store_true",
        help=(
            "allow bounded #pragma-style append fragments for a selected "
            "feature-mode campaign; disabled for ordinary C/C++ runs"
        ),
    )
    parser.add_argument(
        "--regression-test-root", type=Path,
        default=DEFAULT_REGRESSION_TEST_ROOT,
        help=(
            "optional Clang regression-test root used only as model prompt "
            "evidence; test files are never data sources"
        ),
    )
    parser.add_argument(
        "--regression-evidence", action=argparse.BooleanOptionalAction,
        default=True,
        help="attach bounded test trigger evidence to model prompts when found",
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--admit-observed-errors", action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "when a candidate misses its requested target, retain its actual "
            "primary error only if it can itself be distilled and exactly replayed; "
            "disabled by default so gap-targeted campaigns preserve their target"
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
        or args.request_batch_size <= 0
        or args.max_tokens <= 0
        or args.timeout <= 0
    ):
        parser.error("candidate, token, and timeout bounds must be positive")
    if args.vllm_concurrency <= 0:
        parser.error("--vllm-concurrency must be positive")
    if args.verification_workers <= 0:
        parser.error("--verification-workers must be positive")
    context_tokens = tuple(
        args.recipe_context_tokens
        if args.recipe_context_tokens is not None
        else DEFAULT_RECIPE_CONTEXT_TOKENS
    )
    if any(level < 0 for level in context_tokens):
        parser.error("recipe context levels must be non-negative")
    requests = _load(args.requests)
    candidate_round_counts = _candidate_round_counts(
        args.candidates, args.feedback_rounds,
    )
    catalog_error_names = frozenset(entry.name for entry in load_catalog().errors())
    excluded_injector_ids = frozenset(load_excluded_injector_ids(args.exclude_injectors))
    excluded_injector_target_names = load_excluded_injector_target_names(
        args.exclude_injectors,
    )
    backend: ChatBackend
    if args.backend == "vllm":
        backend = VLLMChatBackend(
            "gemma-4-31B-it",
            base_url=args.base_url,
            timeout_s=600.0,
            max_concurrency=args.vllm_concurrency,
        )
    else:
        backend = LocalGemma31BBackend(DEFAULT_GEMMA_31B_SNAPSHOT, seed=args.seed)
    verifier = FuzzlangClangVerifier(args.clang_bin, args.diagtool_bin, args.timeout, clang_c_bin=args.clang_c_bin)
    if args.resume:
        (
            attempts, records, undistillable_records, injectors,
            completed_request_indices,
        ) = _load_resume_checkpoint(args.output_dir)
    else:
        attempts = []
        records = []
        undistillable_records = []
        injectors = {}
        completed_request_indices = set()
    observed_admitted_target_names = set(excluded_injector_target_names)
    observed_admitted_target_names.update(
        FuzzLangInjector.from_dict(row).target_diag
        for row in injectors.values()
    )
    accepted_target_names = _accepted_target_names(injectors)
    duplicate_existing_injector_candidates = 0
    feedback_round_requests = 0
    known_covered_observed_short_circuits = 0
    prefetched_responses: dict[int, list] = {}
    prefetched_baseline_ok: dict[int, bool] = {}
    prefetched_prompt_count = 0
    _write_checkpoint(
        args.output_dir,
        attempts=attempts,
        records=records,
        undistillable_records=undistillable_records,
        injectors=injectors,
    )
    for request_index, request in enumerate(requests):
        if (
            args.request_batch_size > 1
            and request_index % args.request_batch_size == 0
        ):
            # Generate one microbatch, then immediately compiler-gate and
            # checkpoint it below before starting another.  A whole target
            # shard may be much larger than a scheduler time slice, but this
            # boundary makes the completed portion safely resumable.
            batch: list[tuple[int, list[dict[str, str]]]] = []
            stop = min(request_index + args.request_batch_size, len(requests))
            for batch_index in range(request_index, stop):
                if batch_index in completed_request_indices:
                    continue
                batch_request = requests[batch_index]
                if batch_request.diag_name in accepted_target_names:
                    continue
                # Wide mode must not send prompts for a source that fails the
                # core parent-compilation gate.  Cache successful checks so
                # the normal per-request path does not compile them twice.
                baseline = verifier.verify(
                    batch_request.corrected_src,
                    list(batch_request.compile_cmd),
                    logical_path=batch_request.source_path,
                )
                prefetched_baseline_ok[batch_index] = baseline.ok
                if not baseline.ok:
                    continue
                model_request = (
                    with_regression_trigger_evidence(
                        batch_request, args.regression_test_root,
                    )
                    if args.regression_evidence else batch_request
                )
                messages = (
                    build_code_append_messages(
                        model_request,
                        allow_preprocessor_directives=(
                            args.allow_preprocessor_directives
                        ),
                    )
                    if args.witness_mode == "append"
                    else build_code_witness_messages(model_request)
                )
                batch.append((batch_index, messages))
            if batch:
                generated = backend.chat_batch(
                    messages_batch=[messages for _, messages in batch],
                    temperature=args.temperature,
                    max_tokens=args.max_tokens,
                    n=candidate_round_counts[0],
                )
                for (batch_index, _), responses in zip(
                    batch, generated, strict=True,
                ):
                    prefetched_responses[batch_index] = responses
                prefetched_prompt_count += len(batch)
        if request_index in completed_request_indices:
            continue
        if request.diag_name in excluded_injector_target_names:
            attempts.append({
                "request_index": request_index,
                "diag_name": request.diag_name,
                "status": "target_already_covered",
            })
            _write_checkpoint(
                args.output_dir,
                attempts=attempts,
                records=records,
                undistillable_records=undistillable_records,
                injectors=injectors,
            )
            continue
        if request.diag_name in accepted_target_names:
            attempts.append({
                "request_index": request_index,
                "diag_name": request.diag_name,
                "status": "target_already_accepted_in_campaign",
            })
            _write_checkpoint(
                args.output_dir,
                attempts=attempts,
                records=records,
                undistillable_records=undistillable_records,
                injectors=injectors,
            )
            continue
        # Use the actual verified language standard of this source instead of
        # treating every request as ordinary C++17.  That keeps special C/C++
        # dialect targets reachable while preserving an inexpensive guard for
        # clearly incompatible default-mode diagnostics.
        if not _supports_request_compile_mode(
            request,
            allow_preprocessor_directives=args.allow_preprocessor_directives,
        ):
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
        baseline_ok = prefetched_baseline_ok.pop(request_index, None)
        if baseline_ok is None:
            baseline_ok = verifier.verify(
                request.corrected_src,
                list(request.compile_cmd),
                logical_path=request.source_path,
            ).ok
        if not baseline_ok:
            attempts.append({"request_index": request_index, "diag_name": request.diag_name, "status": "baseline_not_clean"})
            _write_checkpoint(
                args.output_dir,
                attempts=attempts,
                records=records,
                undistillable_records=undistillable_records,
                injectors=injectors,
            )
            continue
        model_request = (
            with_regression_trigger_evidence(
                request, args.regression_test_root,
            )
            if args.regression_evidence else request
        )
        messages = (
            build_code_append_messages(
                model_request,
                allow_preprocessor_directives=args.allow_preprocessor_directives,
            )
            if args.witness_mode == "append"
            else build_code_witness_messages(model_request)
        )
        rejection_reasons: set[str] = set()
        observed_diagnostics: set[str] = set()
        accepted = False
        candidate_index = 0
        known_covered_only_streak = 0
        for round_index, candidate_count in enumerate(candidate_round_counts):
            if accepted:
                continue
            if round_index > 0:
                feedback_round_requests += 1
                if args.witness_mode == "append":
                    messages = build_code_append_retry_messages(
                        model_request,
                        rejection_reasons=tuple(rejection_reasons),
                        observed_diagnostics=tuple(observed_diagnostics),
                        allow_preprocessor_directives=(
                            args.allow_preprocessor_directives
                        ),
                    )
                else:
                    messages = build_code_witness_retry_messages(
                        model_request,
                        rejection_reasons=tuple(rejection_reasons),
                        observed_diagnostics=tuple(observed_diagnostics),
                    )
            prefetched = prefetched_responses.get(request_index)
            if round_index == 0 and prefetched:
                responses = prefetched_responses.pop(request_index)
            else:
                responses = backend.chat(
                    messages=messages,
                    temperature=args.temperature,
                    max_tokens=args.max_tokens,
                    n=candidate_count,
                )
            parsed_candidates = []
            candidate_sources: list[str] = []
            for response in responses:
                if args.witness_mode == "append":
                    patch, reason = parse_code_append_fragment(
                        response.text, request,
                    )
                else:
                    patch, reason = parse_code_witness_patch(
                        response.text, request,
                    )
                parsed_candidates.append((response, patch, reason))
                if patch is not None:
                    candidate_sources.append(
                        apply_code_append_fragment(request, patch)
                        if args.witness_mode == "append"
                        else apply_code_witness_patch(request, patch)
                    )
            verified_candidates = iter(_verify_candidate_sources(
                verifier,
                candidate_sources,
                compile_cmd=list(request.compile_cmd),
                logical_path=request.source_path,
                workers=args.verification_workers,
            ))
            round_rejection_reasons: set[str] = set()
            for response, patch, reason in parsed_candidates:
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
                        round_rejection_reasons.add(reason)
                    continue
                erroneous = (
                    apply_code_append_fragment(request, patch)
                    if args.witness_mode == "append"
                    else apply_code_witness_patch(request, patch)
                )
                verified = next(verified_candidates)
                if verified.ok or verified.diag is None:
                    row["status"] = "rejected"
                    row["reason"] = "candidate_clean_or_wrong_primary"
                    row["observed_diag"] = (
                        verified.diag.diag_name if verified.diag else None
                    )
                    attempts.append(row)
                    rejection_reasons.add(row["reason"])
                    round_rejection_reasons.add(row["reason"])
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
                        round_rejection_reasons.add(row["reason"])
                        continue
                    target_diag_name = verified.diag.diag_name
                    if not is_catalog_error_diagnostic_name(
                        target_diag_name, catalog_error_names,
                    ):
                        row["status"] = "rejected"
                        row["reason"] = "observed_diagnostic_not_catalog_error"
                        row["observed_diag"] = target_diag_name
                        attempts.append(row)
                        rejection_reasons.add(row["reason"])
                        round_rejection_reasons.add(row["reason"])
                        continue
                    if target_diag_name in observed_admitted_target_names:
                        row["status"] = "rejected"
                        row["reason"] = "observed_diagnostic_already_covered"
                        row["observed_diag"] = target_diag_name
                        attempts.append(row)
                        rejection_reasons.add(row["reason"])
                        round_rejection_reasons.add(row["reason"])
                        continue
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
                            "strategy": (
                                "gemma_append_witness_bootstrap"
                                if args.witness_mode == "append"
                                else "gemma_code_witness_bootstrap"
                            ),
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
                if args.witness_mode == "append":
                    injector = FuzzLangInjector.append_fragment(
                        target_diag=target_diag_name,
                        diag_id=verified.diag.diag_id,
                        language=request.language,
                        fragment=patch.fragment,
                        exemplar_id=record.record_id,
                    )
                    candidate_injectors[injector.injector_id] = injector
                else:
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
                    round_rejection_reasons.add(row["reason"])
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
                            "strategy": (
                                "gemma_append_witness_injector_replay"
                                if args.witness_mode == "append"
                                else "gemma_code_witness_injector_replay"
                            ),
                            "injector_id": injector.injector_id,
                            "injector_replay_exact": True,
                            "allow_preprocessor_directives": (
                                args.allow_preprocessor_directives
                            ),
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
                accepted_target_names.add(target_diag_name)
                if opportunistic:
                    observed_admitted_target_names.add(target_diag_name)
                accepted = True
                break
            known_covered_only_streak = _known_covered_only_round_streak(
                known_covered_only_streak, round_rejection_reasons,
            )
            if known_covered_only_streak >= 2:
                known_covered_observed_short_circuits += 1
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
    manifest = {"schema": "fuzzlang.code_witness_bootstrap", "model": {"name": DEFAULT_GEMMA_31B_MODEL, "revision": DEFAULT_GEMMA_31B_REVISION, "parameters": "31B"}, "paid_api_calls": False, "witness_mode": args.witness_mode, "allow_preprocessor_directives": args.allow_preprocessor_directives, "request_batch_size": args.request_batch_size, "prefetched_prompt_count": prefetched_prompt_count, "recipe_context_tokens": list(context_tokens), "counts": {"requests": len(requests), "attempts": len(attempts), "records": len(records), "undistillable_records": len(undistillable_records), "portable_injectors": len(injectors), "excluded_injector_identities": len(excluded_injector_ids), "duplicate_existing_injector_candidates": duplicate_existing_injector_candidates, "feedback_round_requests": feedback_round_requests, "known_covered_observed_short_circuits": known_covered_observed_short_circuits}}
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")
    print(json.dumps(manifest["counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
