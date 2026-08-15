"""Replay a released FuzzLang Injector library on real source. No model calls.

This is the E1 engine. It takes the *already released* Injector library — not a
model, not a synthesis loop — and applies it to clean, non-test translation
units, keeping only pairs the pinned compiler confirms. There is deliberately
no backend parameter: a run that needs a model is a different experiment.

Two safety properties matter more than throughput here:

* **Split guard.** Writing a training record from a held-out translation unit
  or a held-out project raises. It never relabels the record to make it fit.
* **Caps.** Per-source and per-diagnostic caps stop one Injector or one file
  from flooding the dataset, so multiplicity reflects real transfer.
"""
from __future__ import annotations

import hashlib
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from foundation.record import Origin, Provenance, Record, Split
from gen.fuzzlang_dsl.injector import FuzzLangInjector, apply_injector
from gen.realcorpus.corpus import is_test_path
from gen.realcorpus.recipes import build_token_index, lex_tokens
from gen.realcorpus.source_splits import EVAL_UNSEEN_TU, HELDOUT_PROJECT, TRAIN

STRATEGY = "fuzzlang_library_replay"
_SPLIT_BY_NAME = {
    TRAIN: Split.TRAIN,
    EVAL_UNSEEN_TU: Split.EVAL,
    HELDOUT_PROJECT: Split.EVAL,
}


@dataclass(frozen=True)
class ReplayCaps:
    max_records_per_source: int = 3
    max_records_per_diagnostic: int = 5
    max_candidates_per_injector: int = 1
    # A full library against a full pool is millions of match attempts, and a
    # compile is ~1000x more expensive than a match.  Bound the expensive side
    # per source so one stubborn file cannot consume the run.
    max_verifications_per_source: int = 24


class DiagnosticBudget:
    """A per-diagnostic record cap shared by every concurrent shard.

    Without sharing, N shards each spend the full cap and the surplus is
    discarded after the merge — which both wastes compiles and hides how many
    verified records the library actually produced.
    """

    def __init__(self, cap: int) -> None:
        if isinstance(cap, bool) or not isinstance(cap, int) or cap <= 0:
            raise ValueError("cap must be a positive integer")
        self.cap = cap
        self._counts: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def claim(self, diagnostic: str) -> bool:
        """Reserve one slot for ``diagnostic``; False when it is exhausted."""
        with self._lock:
            if self._counts[diagnostic] >= self.cap:
                return False
            self._counts[diagnostic] += 1
            return True

    def release(self, diagnostic: str) -> None:
        """Give a reserved slot back when the compiler rejected the candidate."""
        with self._lock:
            self._counts[diagnostic] = max(0, self._counts[diagnostic] - 1)

    def counts(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)


def order_library_for_coverage(
    injectors: Sequence[FuzzLangInjector],
) -> list[FuzzLangInjector]:
    """Interleave Injectors so consecutive ones target different diagnostics.

    The per-source verification budget is the scarce resource. In archive order
    a source can spend all of it on Injectors for the same handful of targets;
    round-robin spends it on as many distinct diagnostics as it has compiles.
    """
    grouped: dict[str, list[FuzzLangInjector]] = defaultdict(list)
    for injector in sorted(injectors, key=lambda item: item.injector_id):
        grouped[injector.target_diag].append(injector)
    ordered: list[FuzzLangInjector] = []
    for round_index in range(max((len(v) for v in grouped.values()), default=0)):
        for diagnostic in sorted(grouped):
            bucket = grouped[diagnostic]
            if round_index < len(bucket):
                ordered.append(bucket[round_index])
    return ordered


@dataclass
class ReplayBudget:
    """Model cost is structurally zero here; only compilation is spent."""

    model_calls: int = 0
    output_tokens: int = 0
    compiler_invocations: int = 0

    def to_dict(self) -> dict:
        return {
            "model_calls": self.model_calls,
            "output_tokens": self.output_tokens,
            "compiler_invocations": self.compiler_invocations,
        }


@dataclass
class ReplayResult:
    records: list[Record] = field(default_factory=list)
    rejections: dict[str, int] = field(default_factory=dict)
    reach: dict[str, dict] = field(default_factory=dict)
    budget: ReplayBudget = field(default_factory=ReplayBudget)

    def summary(self) -> dict:
        diagnostics = {r.provenance.detail["target_diag"] for r in self.records}
        projects = {r.provenance.detail["project"] for r in self.records}
        sources = {r.provenance.source for r in self.records}
        return {
            "records": len(self.records),
            "diagnostics": len(diagnostics),
            "projects": len(projects),
            "source_tus": len(sources),
            "injectors_that_produced_a_record": len(self.reach),
            "zero_model_calls": self.budget.model_calls == 0,
            "budget": self.budget.to_dict(),
            "rejections": dict(sorted(self.rejections.items())),
            "compiler_invocations_per_record": (
                round(self.budget.compiler_invocations / len(self.records), 4)
                if self.records else None
            ),
        }


def load_injector_library(paths: Iterable[Path]) -> tuple[FuzzLangInjector, ...]:
    """Load portable Injectors from archived JSONL, first occurrence winning."""
    library: dict[str, FuzzLangInjector] = {}
    for path in paths:
        for number, line in enumerate(Path(path).read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                injector = FuzzLangInjector.from_json(line)
            except ValueError as error:
                raise ValueError(f"{path}:{number}: invalid Injector: {error}") from error
            if injector.portable:
                library.setdefault(injector.injector_id, injector)
    return tuple(library.values())


def _check_split(source: Mapping, split: str) -> None:
    actual = source.get("split")
    if actual is None:
        raise ValueError(
            f"{source['source_id']} has no frozen split; run "
            "run_freeze_source_splits.py before generating"
        )
    if actual != split:
        raise ValueError(
            f"refusing to emit a '{split}' record from held-out source "
            f"{source['source_id']} (split={actual})"
        )


def replay_library(
    injectors: Sequence[FuzzLangInjector],
    sources: Sequence[Mapping],
    verifier,
    *,
    caps: ReplayCaps,
    split: str = TRAIN,
    diagnostic_budget: "DiagnosticBudget | None" = None,
) -> ReplayResult:
    """Apply every Injector to every eligible source, compiler-verified."""
    budget = diagnostic_budget or DiagnosticBudget(caps.max_records_per_diagnostic)
    result = ReplayResult()
    rejections: dict[str, int] = defaultdict(int)
    reach: dict[str, dict[str, set]] = defaultdict(
        lambda: {"sources": set(), "projects": set()}
    )
    per_source: dict[str, int] = defaultdict(int)
    per_diagnostic: dict[str, int] = defaultdict(int)

    for source in sources:
        _check_split(source, split)
        if is_test_path(source["source_path"]) or is_test_path(source["source_id"]):
            raise ValueError(
                f"{source['source_id']} is a test or test-support path and "
                "must never be a dataset source"
            )

    for source in sources:
        # Tokenize each translation unit once and share the index across the
        # whole library; re-lexing a large file per Injector dominated runtime.
        tokens = lex_tokens(source["corrected_src"])
        token_index = build_token_index(tokens)
        verifications = 0
        for injector in injectors:
            if per_source[source["source_id"]] >= caps.max_records_per_source:
                break
            if verifications >= caps.max_verifications_per_source:
                rejections["source_verification_budget_exhausted"] += 1
                break
            if injector.language != source.get("language"):
                continue
            if not budget.claim(injector.target_diag):
                rejections["diagnostic_budget_exhausted"] += 1
                continue
            applications = apply_injector(
                source["corrected_src"], injector,
                max_candidates=caps.max_candidates_per_injector,
                tokens=tokens, token_index=token_index,
            )
            if not applications:
                budget.release(injector.target_diag)
                rejections["injector_does_not_match_source"] += 1
                continue
            erroneous = applications[0].src
            verified = verifier.verify(
                erroneous, list(source["compile_cmd"]),
                logical_path=source["source_path"],
            )
            result.budget.compiler_invocations += 1
            verifications += 1
            reason = _rejection(verified, injector)
            if reason is not None:
                budget.release(injector.target_diag)
                rejections[reason] += 1
                continue
            result.records.append(_record(source, injector, erroneous, verified.diag, split))
            per_source[source["source_id"]] += 1
            per_diagnostic[injector.target_diag] += 1
            reach[injector.injector_id]["sources"].add(source["source_id"])
            reach[injector.injector_id]["projects"].add(source["project"])

    result.rejections = dict(rejections)
    result.reach = {
        injector_id: {
            "sources": len(spread["sources"]),
            "projects": sorted(spread["projects"]),
        }
        for injector_id, spread in sorted(reach.items())
    }
    return result


def _rejection(verified, injector: FuzzLangInjector) -> str | None:
    if verified.ok or verified.diag is None:
        return "mutant_compiles_clean"
    if verified.diag.diag_name != injector.target_diag:
        return "wrong_primary_diagnostic"
    if (
        injector.target_diag_id is not None
        and verified.diag.diag_id != injector.target_diag_id
    ):
        return "wrong_primary_diag_id"
    return None


def _record(
    source: Mapping, injector: FuzzLangInjector, erroneous: str, diag, split: str,
) -> Record:
    return Record(
        record_id="library-replay-" + hashlib.sha256(
            (source["source_id"] + "\0" + injector.injector_id + "\0" + erroneous).encode()
        ).hexdigest()[:24],
        erroneous_src=erroneous,
        corrected_src=source["corrected_src"],
        diagnostics=(diag,),
        split=_SPLIT_BY_NAME[split],
        language=source["language"],
        provenance=Provenance(
            origin=Origin.MUTATE,
            source=source["source_id"],
            detail={
                "strategy": STRATEGY,
                "experiment": "e1",
                "project": source["project"],
                "source_path": source["source_path"],
                "compile_cmd": list(source["compile_cmd"]),
                "target_diag": injector.target_diag,
                "primary_matches_target": True,
                "opportunistic_observed_diagnostic": False,
                "injector_id": injector.injector_id,
                "injector_schema_version": injector.schema_version,
                "source_split": split,
            },
        ),
    )
