"""Experiment E1: reusable Injector synthesis versus per-record DirectEdit.

Both arms are driven from the *same* frozen request set, so they see identical
target diagnostics, identical clean non-test real source windows, and the same
TableGen/emission evidence.  They differ only in how the model is spent:

``direct_edit``
    one model call per (diagnostic, source): the model edits that specific
    window and the compiler judges that specific mutant.
``injector``
    one model call per diagnostic: the model emits a reusable FuzzLang DSL
    Injector, which is then replayed on every source with no further model
    work.

Acceptance is identical and deliberately strict for both arms: the parent must
compile clean, the mutant must fail, and the primary typed diagnostic must
equal the *requested* target (name, and DiagID where the request pins one).
An opportunistically observed different diagnostic is never relabelled as a
success.  Every model call, compiler invocation, and second of model time is
attributed to the arm that spent it.
"""
from __future__ import annotations

import hashlib
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

from foundation.record import Origin, Provenance, Record, Split
from gen.fuzzlang_dsl.code_witness import (
    CodeWitnessRequest, apply_code_witness_patch, build_code_witness_messages,
    parse_code_witness_patch,
)
from gen.fuzzlang_dsl.injector import FuzzLangInjector, apply_injector
from gen.fuzzlang_dsl.synthesis import (
    DiagnosticEvidence, SynthesisRequest, synthesize_injectors,
)

DIRECT_EDIT_STRATEGY = "gemma_localized_direct_edit"
INJECTOR_STRATEGY = "e1_injector_replay"


@dataclass
class E1Budget:
    """What one arm actually consumed, in the units the comparison needs."""

    model_calls: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    model_seconds: float = 0.0
    compiler_invocations: int = 0
    compiler_seconds: float = 0.0

    def add_model(self, *, output_tokens: int, prompt_tokens: int, seconds: float) -> None:
        self.model_calls += 1
        self.output_tokens += output_tokens
        self.prompt_tokens += prompt_tokens
        self.model_seconds += seconds

    def add_compile(self, seconds: float) -> None:
        self.compiler_invocations += 1
        self.compiler_seconds += seconds

    def efficiency(self, *, accepted_records: int) -> dict:
        """Normalize yield by the two budgets the plan requires E1 to report."""
        hours = self.model_seconds / 3600.0
        return {
            "records_per_1k_output_tokens": (
                round(1000.0 * accepted_records / self.output_tokens, 4)
                if self.output_tokens else 0.0
            ),
            "records_per_gpu_hour": (
                round(accepted_records / hours, 4) if hours > 0 else None
            ),
            "output_tokens_per_accepted_record": (
                round(self.output_tokens / accepted_records, 2)
                if accepted_records else None
            ),
            "compiler_invocations_per_accepted_record": (
                round(self.compiler_invocations / accepted_records, 4)
                if accepted_records else None
            ),
            "model_calls_per_accepted_record": (
                round(self.model_calls / accepted_records, 4)
                if accepted_records else None
            ),
        }

    def to_dict(self) -> dict:
        return {
            "model_calls": self.model_calls,
            "prompt_tokens": self.prompt_tokens,
            "output_tokens": self.output_tokens,
            "model_seconds": round(self.model_seconds, 3),
            "compiler_invocations": self.compiler_invocations,
            "compiler_seconds": round(self.compiler_seconds, 3),
        }


@dataclass(frozen=True)
class E1Attempt:
    """One auditable unit of work: a model candidate or an Injector replay."""

    arm: str
    target: str
    stage: str
    source_id: str
    project: str
    candidate_index: int
    status: str
    reason: Optional[str] = None
    observed_diag: Optional[str] = None
    observed_diag_id: Optional[int] = None
    output_tokens: int = 0
    injector_id: Optional[str] = None
    response_text: Optional[str] = None
    compile_cmd: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "arm": self.arm, "target": self.target, "stage": self.stage,
            "source_id": self.source_id, "project": self.project,
            "candidate_index": self.candidate_index, "status": self.status,
            "reason": self.reason, "observed_diag": self.observed_diag,
            "observed_diag_id": self.observed_diag_id,
            "output_tokens": self.output_tokens,
            "injector_id": self.injector_id,
            "response_text": self.response_text,
            "compile_cmd": list(self.compile_cmd),
        }


@dataclass
class ArmResult:
    arm: str
    records: list[Record] = field(default_factory=list)
    injectors: list[FuzzLangInjector] = field(default_factory=list)
    attempts: list[E1Attempt] = field(default_factory=list)
    budget: E1Budget = field(default_factory=E1Budget)
    per_target: dict[str, dict] = field(default_factory=dict)
    wall_seconds: float = 0.0

    def merge(self, other: "ArmResult") -> None:
        self.records.extend(other.records)
        self.injectors.extend(other.injectors)
        self.attempts.extend(other.attempts)
        self.per_target.update(other.per_target)
        for name in (
            "model_calls", "prompt_tokens", "output_tokens", "model_seconds",
            "compiler_invocations", "compiler_seconds",
        ):
            setattr(
                self.budget, name,
                getattr(self.budget, name) + getattr(other.budget, name),
            )

    def summary(self) -> dict:
        targets = len(self.per_target)
        with_record = sum(
            1 for stats in self.per_target.values() if stats["accepted_records"]
        )
        return {
            "arm": self.arm,
            "targets": targets,
            "targets_with_accepted_record": with_record,
            "target_hit_rate": round(with_record / targets, 4) if targets else 0.0,
            "accepted_records": len(self.records),
            "accepted_injectors": len(self.injectors),
            # ``model_seconds`` sums per-call durations; under fan-out those
            # overlap, so it is the serial-equivalent model cost.  Wall time is
            # reported separately and is the honest allocation cost.
            "wall_seconds": round(self.wall_seconds, 3),
            "budget": self.budget.to_dict(),
            "efficiency": self.budget.efficiency(
                accepted_records=len(self.records),
            ),
        }


def _fan_out(
    arm: str, targets: Sequence[str], worker, max_workers: int,
) -> ArmResult:
    """Run independent per-target work and merge it into one arm result."""
    result = ArmResult(arm=arm)
    started = time.monotonic()
    if max_workers <= 1:
        shards = [worker(target) for target in targets]
    else:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(targets))) as pool:
            shards = list(pool.map(worker, targets))
    for shard in shards:
        result.merge(shard)
    result.wall_seconds = time.monotonic() - started
    result.records.sort(key=lambda record: record.record_id)
    result.attempts.sort(key=lambda item: (item.target, item.source_id, item.candidate_index))
    return result


def _verify(verifier, budget: E1Budget, source: str, request: CodeWitnessRequest):
    started = time.monotonic()
    result = verifier.verify(
        source, list(request.compile_cmd), logical_path=request.source_path,
    )
    budget.add_compile(time.monotonic() - started)
    return result


def _acceptance_reason(result, request: CodeWitnessRequest) -> Optional[str]:
    """Why a mutant is not an accepted record for its *requested* target."""
    if result.ok or result.diag is None:
        return "mutant_compiles_clean"
    if result.diag.diag_name != request.diag_name:
        return "wrong_primary_diagnostic"
    if request.diag_id is not None and result.diag.diag_id != request.diag_id:
        return "wrong_primary_diag_id"
    return None


def _record(
    request: CodeWitnessRequest, erroneous: str, diag, *,
    strategy: str, injector: FuzzLangInjector | None,
) -> Record:
    # A per-record localized model edit is exactly what `llm_localized_edit`
    # denotes, so this path carries the canonical DirectEdit provenance the SFT
    # arm builder recognizes.  Injector replay stays a MUTATE-origin record:
    # no model was involved in producing it.
    direct_edit = strategy == DIRECT_EDIT_STRATEGY
    detail = {
        "strategy": strategy,
        "experiment": "e1",
        "project": request.project,
        "source_path": request.source_path,
        "compile_cmd": list(request.compile_cmd),
        "target_diag": request.diag_name,
        "primary_matches_target": True,
        "opportunistic_observed_diagnostic": False,
    }
    if direct_edit:
        detail["generator"] = "llm_localized_edit"
    if injector is not None:
        detail["injector_id"] = injector.injector_id
        detail["injector_schema_version"] = injector.schema_version
    return Record(
        record_id=strategy.replace("_", "-") + "-" + hashlib.sha256(
            (request.source_id + "\0" + request.diag_name + "\0" + erroneous).encode()
        ).hexdigest()[:24],
        erroneous_src=erroneous,
        corrected_src=request.corrected_src,
        diagnostics=(diag,),
        split=Split.TRAIN,
        language=request.language,
        provenance=Provenance(
            origin=Origin.LLM if direct_edit else Origin.MUTATE,
            source=request.source_id,
            detail=detail,
        ),
    )


def _clean_parent(
    request: CodeWitnessRequest, verifier, budget: E1Budget,
    cache: dict[str, bool],
) -> bool:
    """Re-gate the parent once per source so a stale pool cannot leak in."""
    if request.source_id not in cache:
        cache[request.source_id] = bool(
            _verify(verifier, budget, request.corrected_src, request).ok
        )
    return cache[request.source_id]


def run_direct_edit_arm(
    requests: Mapping[str, Sequence[CodeWitnessRequest]],
    backend,
    verifier,
    *,
    candidates: int,
    temperature: float,
    max_tokens: int,
    evidence_sources: int = 2,
    prompt_token_counter=None,
    max_workers: int = 1,
) -> ArmResult:
    """Spend one model call per (diagnostic, source) and verify each mutant."""

    def worker(target: str) -> ArmResult:
        return _direct_edit_target(
            target, requests[target], backend, verifier,
            candidates=candidates, temperature=temperature,
            max_tokens=max_tokens, evidence_sources=evidence_sources,
            prompt_token_counter=prompt_token_counter,
        )

    return _fan_out("direct_edit", list(requests), worker, max_workers)


def _direct_edit_target(
    target: str,
    target_requests: Sequence[CodeWitnessRequest],
    backend,
    verifier,
    *,
    candidates: int,
    temperature: float,
    max_tokens: int,
    evidence_sources: int = 2,
    prompt_token_counter=None,
) -> ArmResult:
    result = ArmResult(arm="direct_edit")
    clean_cache: dict[str, bool] = {}
    stats = _new_stats(target_requests, evidence_sources=evidence_sources)
    for request in target_requests:
        if not _clean_parent(request, verifier, result.budget, clean_cache):
            result.attempts.append(E1Attempt(
                arm="direct_edit", target=target, stage="clean_gate",
                source_id=request.source_id, project=request.project,
                candidate_index=-1, status="rejected",
                reason="parent_does_not_compile",
                compile_cmd=request.compile_cmd,
            ))
            continue
        messages = build_code_witness_messages(request)
        prompt_tokens = (
            prompt_token_counter(messages) if prompt_token_counter else 0
        )
        started = time.monotonic()
        try:
            responses = backend.chat(
                messages=messages, temperature=temperature,
                max_tokens=max_tokens, n=candidates,
            )
        except Exception as error:
            # One endpoint failure must cost one source, not the whole arm:
            # a partially completed E1 run is still analysable, an aborted
            # one is not.
            result.budget.add_model(
                output_tokens=0, prompt_tokens=prompt_tokens,
                seconds=time.monotonic() - started,
            )
            stats["model_calls"] += 1
            stats["failed_model_calls"] += 1
            result.attempts.append(E1Attempt(
                arm="direct_edit", target=target, stage="model",
                source_id=request.source_id, project=request.project,
                candidate_index=-1, status="rejected",
                reason="model_call_failed",
                response_text=" ".join(str(error).split())[:2000],
                compile_cmd=request.compile_cmd,
            ))
            continue
        result.budget.add_model(
            output_tokens=sum(item.output_tokens for item in responses),
            prompt_tokens=prompt_tokens,
            seconds=time.monotonic() - started,
        )
        stats["model_calls"] += 1
        accepted = _direct_edit_candidates(
            target, request, responses, verifier, result,
        )
        if accepted is not None:
            result.records.append(accepted)
            stats["accepted_records"] += 1
            stats["accepted_sources"].add(request.source_id)
            if request.project != stats["primary_project"]:
                stats["transfer_sources"].add(request.source_id)
    result.per_target[target] = _finalize_stats(stats)
    return result


def _direct_edit_candidates(
    target: str, request: CodeWitnessRequest, responses, verifier,
    result: ArmResult,
) -> Optional[Record]:
    for index, response in enumerate(responses):
        patch, reason = parse_code_witness_patch(response.text, request)
        if patch is None:
            result.attempts.append(E1Attempt(
                arm="direct_edit", target=target, stage="model",
                source_id=request.source_id, project=request.project,
                candidate_index=index, status="rejected", reason=reason,
                output_tokens=response.output_tokens,
                response_text=response.text, compile_cmd=request.compile_cmd,
            ))
            continue
        erroneous = apply_code_witness_patch(request, patch)
        verified = _verify(verifier, result.budget, erroneous, request)
        rejection = _acceptance_reason(verified, request)
        result.attempts.append(E1Attempt(
            arm="direct_edit", target=target, stage="model",
            source_id=request.source_id, project=request.project,
            candidate_index=index,
            status="accepted" if rejection is None else "rejected",
            reason=rejection,
            observed_diag=verified.diag.diag_name if verified.diag else None,
            observed_diag_id=verified.diag.diag_id if verified.diag else None,
            output_tokens=response.output_tokens,
            response_text=response.text, compile_cmd=request.compile_cmd,
        ))
        if rejection is None:
            return _record(
                request, erroneous, verified.diag,
                strategy=DIRECT_EDIT_STRATEGY, injector=None,
            )
    return None


def run_injector_arm(
    requests: Mapping[str, Sequence[CodeWitnessRequest]],
    backend,
    verifier,
    *,
    candidates: int,
    temperature: float,
    max_tokens: int,
    evidence_sources: int = 2,
    prompt_token_counter=None,
    max_workers: int = 1,
) -> ArmResult:
    """Spend one model call per diagnostic, then replay with the compiler only."""
    if evidence_sources < 1:
        raise ValueError("an Injector request needs at least one source window")

    def worker(target: str) -> ArmResult:
        return _injector_target(
            target, requests[target], backend, verifier,
            candidates=candidates, temperature=temperature,
            max_tokens=max_tokens, evidence_sources=evidence_sources,
            prompt_token_counter=prompt_token_counter,
        )

    return _fan_out("injector", list(requests), worker, max_workers)


def _injector_target(
    target: str,
    target_requests: Sequence[CodeWitnessRequest],
    backend,
    verifier,
    *,
    candidates: int,
    temperature: float,
    max_tokens: int,
    evidence_sources: int,
    prompt_token_counter=None,
) -> ArmResult:
    result = ArmResult(arm="injector")
    clean_cache: dict[str, bool] = {}
    stats = _new_stats(target_requests, evidence_sources=evidence_sources)
    evidence = list(target_requests[:evidence_sources])
    if not evidence:
        result.per_target[target] = _finalize_stats(stats)
        return result
    synthesis_request = _synthesis_request(evidence)
    started = time.monotonic()
    try:
        synthesis = synthesize_injectors(
            synthesis_request, backend, n_candidates=candidates,
            temperature=temperature, max_tokens=max_tokens,
            prompt_token_counter=prompt_token_counter,
        )
    except Exception as error:
        result.budget.add_model(
            output_tokens=0, prompt_tokens=0,
            seconds=time.monotonic() - started,
        )
        stats["model_calls"] += 1
        stats["failed_model_calls"] += 1
        result.attempts.append(E1Attempt(
            arm="injector", target=target, stage="model",
            source_id="", project=stats["primary_project"],
            candidate_index=-1, status="rejected", reason="model_call_failed",
            response_text=" ".join(str(error).split())[:2000],
        ))
        result.per_target[target] = _finalize_stats(stats)
        return result
    result.budget.add_model(
        output_tokens=synthesis.usage.output_tokens,
        prompt_tokens=synthesis.usage.prompt_tokens or 0,
        seconds=time.monotonic() - started,
    )
    stats["model_calls"] += 1
    accepted_per_source: dict[str, Record] = {}
    for attempt in synthesis.attempts:
        if attempt.injector is None:
            result.attempts.append(E1Attempt(
                arm="injector", target=target, stage="model",
                source_id="", project=stats["primary_project"],
                candidate_index=attempt.candidate_index, status="rejected",
                reason=attempt.reason, output_tokens=attempt.output_tokens,
                response_text=attempt.raw_text,
            ))
            continue
        injector = attempt.injector
        result.attempts.append(E1Attempt(
            arm="injector", target=target, stage="model",
            source_id="", project=stats["primary_project"],
            candidate_index=attempt.candidate_index, status="accepted",
            output_tokens=attempt.output_tokens,
            injector_id=injector.injector_id, response_text=attempt.raw_text,
        ))
        result.injectors.append(injector)
        stats["accepted_injectors"] += 1
        if _replay_injector(
            target, injector, target_requests, verifier, result,
            clean_cache, accepted_per_source, stats,
        ):
            stats["replaying_injectors"] += 1
    for source_id, record in accepted_per_source.items():
        result.records.append(record)
        stats["accepted_records"] += 1
        stats["accepted_sources"].add(source_id)
        if record.provenance.detail["project"] != stats["primary_project"]:
            stats["transfer_sources"].add(source_id)
    result.per_target[target] = _finalize_stats(stats)
    return result


def _replay_injector(
    target: str, injector: FuzzLangInjector,
    target_requests: Sequence[CodeWitnessRequest], verifier, result: ArmResult,
    clean_cache: dict[str, bool], accepted_per_source: dict[str, Record],
    stats: dict,
) -> bool:
    replayed = False
    for request in target_requests:
        if request.source_id in accepted_per_source:
            continue
        if not _clean_parent(request, verifier, result.budget, clean_cache):
            result.attempts.append(E1Attempt(
                arm="injector", target=target, stage="clean_gate",
                source_id=request.source_id, project=request.project,
                candidate_index=-1, status="rejected",
                reason="parent_does_not_compile",
                injector_id=injector.injector_id,
                compile_cmd=request.compile_cmd,
            ))
            continue
        applications = apply_injector(
            request.corrected_src, injector, max_candidates=1,
        )
        if not applications:
            result.attempts.append(E1Attempt(
                arm="injector", target=target, stage="replay",
                source_id=request.source_id, project=request.project,
                candidate_index=0, status="rejected",
                reason="injector_does_not_match_source",
                injector_id=injector.injector_id,
                compile_cmd=request.compile_cmd,
            ))
            continue
        erroneous = applications[0].src
        verified = _verify(verifier, result.budget, erroneous, request)
        rejection = _acceptance_reason(verified, request)
        result.attempts.append(E1Attempt(
            arm="injector", target=target, stage="replay",
            source_id=request.source_id, project=request.project,
            candidate_index=0,
            status="accepted" if rejection is None else "rejected",
            reason=rejection,
            observed_diag=verified.diag.diag_name if verified.diag else None,
            observed_diag_id=verified.diag.diag_id if verified.diag else None,
            injector_id=injector.injector_id, compile_cmd=request.compile_cmd,
        ))
        if rejection is None:
            accepted_per_source[request.source_id] = _record(
                request, erroneous, verified.diag,
                strategy=INJECTOR_STRATEGY, injector=injector,
            )
            replayed = True
    return replayed


def _synthesis_request(evidence: Sequence[CodeWitnessRequest]) -> SynthesisRequest:
    first = evidence[0]
    return SynthesisRequest(
        diag_name=first.diag_name,
        diag_id=first.diag_id,
        diag_message=first.diag_message,
        component=first.component,
        language=first.language,
        correct_snippets=tuple(request.window for request in evidence),
        evidence=DiagnosticEvidence(
            tablegen_definition=first.tablegen_definition,
            emission_evidence=first.emission_evidence,
        ),
        single_witness_long_tail=len(evidence) == 1,
    )


def _new_stats(
    target_requests: Sequence[CodeWitnessRequest], *, evidence_sources: int,
) -> dict:
    projects = [request.project for request in target_requests]
    return {
        "primary_project": projects[0] if projects else "",
        "attempted_sources": len(target_requests),
        "evidence_sources": min(evidence_sources, len(target_requests)),
        # The Injector arm's first sources also supply its synthesis prompt.
        # Both arms mark the same split so held-out reuse stays comparable.
        "held_out_source_ids": {
            request.source_id
            for request in target_requests[evidence_sources:]
        },
        "model_calls": 0,
        "failed_model_calls": 0,
        "accepted_records": 0,
        "accepted_injectors": 0,
        "replaying_injectors": 0,
        "accepted_sources": set(),
        "transfer_sources": set(),
        "available_transfer_sources": sum(
            1 for request in target_requests
            if projects and request.project != projects[0]
        ),
    }


def _finalize_stats(stats: dict) -> dict:
    accepted = stats["accepted_records"]
    attempted = stats["attempted_sources"]
    transfer_available = stats["available_transfer_sources"]
    transfer = len(stats["transfer_sources"])
    held_out_available = len(stats["held_out_source_ids"])
    held_out = len(stats["accepted_sources"] & stats["held_out_source_ids"])
    return {
        "primary_project": stats["primary_project"],
        "attempted_sources": attempted,
        "failed_model_calls": stats["failed_model_calls"],
        "evidence_sources": stats["evidence_sources"],
        "held_out_sources": held_out,
        "available_held_out_sources": held_out_available,
        "held_out_source_rate": (
            round(held_out / held_out_available, 4) if held_out_available else None
        ),
        "model_calls": stats["model_calls"],
        "accepted_records": accepted,
        "accepted_injectors": stats["accepted_injectors"],
        "replaying_injectors": stats["replaying_injectors"],
        "replay_sources": len(stats["accepted_sources"]),
        "transfer_sources": transfer,
        "available_transfer_sources": transfer_available,
        "exact_target_rate_per_source": (
            round(accepted / attempted, 4) if attempted else 0.0
        ),
        "transfer_rate": (
            round(transfer / transfer_available, 4) if transfer_available else None
        ),
    }


def compare_arms(arms: Sequence[ArmResult]) -> dict:
    """One comparable table plus the per-diagnostic detail behind it."""
    by_target: dict[str, dict] = defaultdict(dict)
    for arm in arms:
        for target, stats in arm.per_target.items():
            by_target[target][arm.arm] = stats
    return {
        "arms": [arm.summary() for arm in arms],
        "per_target": dict(sorted(by_target.items())),
    }
