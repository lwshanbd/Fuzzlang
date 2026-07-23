"""Bounded replay campaigns for synthesized FuzzLang Injectors.

The campaign consumes canonical Injector artifacts and paired Records whose
``corrected_src`` is a real translation unit.  It never trusts either side:
the corrected TU must compile cleanly, and every injected candidate is
recompiled.  Only candidates whose primary typed diagnostic exactly matches
the Injector target become dataset Records.
"""
from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from foundation.record import Origin, Provenance, Record, Split
from foundation.verifier.base import BaseVerifier
from gen.fuzzlang_dsl.injector import FuzzLangInjector, apply_injector
from gen.realcorpus.clean_source_pool import CleanSourceTU
from gen.realcorpus.corpus import is_test_path
from gen.realcorpus.recipes import LexToken, build_token_index, lex_tokens


@dataclass(frozen=True)
class CampaignBudget:
    """Hard caps for one campaign.

    Verification caps count mutant compilations.  Baseline compilations are
    separately reported because the clean-source gate is mandatory and each
    unique TU is checked at most once.
    """

    max_verifications: int = 10_000
    max_verifications_per_injector: int = 50
    max_sources_per_injector: int = 10_000
    max_candidates_per_source: int = 8
    max_records: int = 10_000
    max_records_per_injector: int = 50
    max_records_per_diagnostic: int = 10_000

    def __post_init__(self) -> None:
        for name in (
            "max_verifications",
            "max_verifications_per_injector",
            "max_sources_per_injector",
            "max_candidates_per_source",
            "max_records",
            "max_records_per_injector",
            "max_records_per_diagnostic",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

    def to_dict(self) -> dict[str, int]:
        return {
            "max_verifications": self.max_verifications,
            "max_verifications_per_injector": self.max_verifications_per_injector,
            "max_sources_per_injector": self.max_sources_per_injector,
            "max_candidates_per_source": self.max_candidates_per_source,
            "max_records": self.max_records,
            "max_records_per_injector": self.max_records_per_injector,
            "max_records_per_diagnostic": self.max_records_per_diagnostic,
        }


@dataclass
class InjectorMetrics:
    injector_id: str
    target_diag: str
    considered: int = 0
    matched: int = 0
    candidates: int = 0
    compiled: int = 0
    exact_target: int = 0
    records_emitted: int = 0
    duplicate_exact: int = 0
    near_miss: int = 0
    clean: int = 0
    _unique_tus: set[str] = field(default_factory=set, repr=False)
    _projects: set[str] = field(default_factory=set, repr=False)

    @property
    def unique_TUs(self) -> int:
        return len(self._unique_tus)

    @property
    def projects(self) -> int:
        return len(self._projects)

    @property
    def target_rate(self) -> float:
        return self.exact_target / self.compiled if self.compiled else 0.0

    def note_exact(self, source: str, project: str) -> None:
        self._unique_tus.add(source)
        self._projects.add(project)

    def to_dict(self) -> dict[str, Any]:
        return {
            "injector_id": self.injector_id,
            "target_diag": self.target_diag,
            "considered": self.considered,
            "matched": self.matched,
            "candidates": self.candidates,
            "compiled": self.compiled,
            "exact_target": self.exact_target,
            "records_emitted": self.records_emitted,
            "duplicate_exact": self.duplicate_exact,
            "near_miss": self.near_miss,
            "clean": self.clean,
            "unique_TUs": self.unique_TUs,
            "projects": self.projects,
            "target_rate": self.target_rate,
        }


@dataclass(frozen=True)
class CampaignRejection:
    status: str
    reason: str
    injector_id: str | None = None
    parent_record_id: str | None = None
    provenance_source: str | None = None
    source_path: str | None = None
    candidate_index: int | None = None
    candidate_sha256: str | None = None
    observed_diag: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "status": self.status,
                "reason": self.reason,
                "injector_id": self.injector_id,
                "parent_record_id": self.parent_record_id,
                "provenance_source": self.provenance_source,
                "source_path": self.source_path,
                "candidate_index": self.candidate_index,
                "candidate_sha256": self.candidate_sha256,
                "observed_diag": self.observed_diag,
            }.items()
            if value is not None
        }


@dataclass(frozen=True)
class CampaignResult:
    records: tuple[Record, ...]
    rejections: tuple[CampaignRejection, ...]
    injector_metrics: tuple[InjectorMetrics, ...]
    budget_usage: Mapping[str, int]
    source_pool: Mapping[str, int]


@dataclass(frozen=True)
class _SourceTU:
    source_id: str
    parent_record_id: str | None
    corrected_src: str
    compile_cmd: list[str]
    source_path: str
    project: str
    language: str
    split: Split
    provenance_detail: Mapping[str, Any]
    source_kind: str
    source_sha256: str | None = None


class _SourceTokenCache:
    """Cache lexical indexes across many Injector passes over one source pool."""

    def __init__(self, maximum_entries: int) -> None:
        self._maximum_entries = max(1, maximum_entries)
        self._entries: OrderedDict[
            str, tuple[list[LexToken], dict[str, tuple[int, ...]]],
        ] = OrderedDict()

    def get(
        self, source: _SourceTU,
    ) -> tuple[list[LexToken], dict[str, tuple[int, ...]]]:
        cached = self._entries.pop(source.source_id, None)
        if cached is None:
            tokens = lex_tokens(source.corrected_src)
            cached = tokens, build_token_index(tokens)
        self._entries[source.source_id] = cached
        if len(self._entries) > self._maximum_entries:
            self._entries.popitem(last=False)
        return cached


def load_injectors_jsonl(path: str | Path) -> list[FuzzLangInjector]:
    """Load canonical Injector JSONL with line-numbered parse failures."""
    injectors: list[FuzzLangInjector] = []
    for line_number, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            injectors.append(FuzzLangInjector.from_json(line))
        except ValueError as error:
            raise ValueError(f"{path}:{line_number}: {error}") from error
    return injectors


def load_records_jsonl(path: str | Path) -> list[Record]:
    """Load canonical paired Record JSONL with line-numbered parse failures."""
    records: list[Record] = []
    for line_number, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("a dataset Record must be a JSON object")
            records.append(Record.from_dict(value))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError(f"{path}:{line_number}: invalid Record: {error}") from error
    return records


def run_campaign(
    injectors: Sequence[FuzzLangInjector],
    source_records: Sequence[Record],
    verifier: BaseVerifier,
    *,
    clean_sources: Sequence[CleanSourceTU] = (),
    clean_source_split: Split = Split.TRAIN,
    budget: CampaignBudget | None = None,
) -> CampaignResult:
    """Replay Injectors on verified-clean, non-test real translation units."""
    if not isinstance(clean_source_split, Split) or clean_source_split is Split.AUXILIARY:
        raise ValueError("clean_source_split must be a core Record split")
    budget = budget or CampaignBudget()
    rejections: list[CampaignRejection] = []
    sources = _prepare_source_pool(source_records, rejections)
    sources.extend(_prepare_clean_source_pool(
        clean_sources,
        rejections,
        seen={source.source_id for source in sources},
        split=clean_source_split,
    ))
    token_cache = _SourceTokenCache(maximum_entries=len(sources))
    unique_injectors = _deduplicate_injectors(injectors, rejections)
    metrics_by_id = {
        injector.injector_id: InjectorMetrics(
            injector_id=injector.injector_id,
            target_diag=injector.target_diag,
        )
        for injector in unique_injectors
    }

    output: list[Record] = []
    output_ids: set[str] = set()
    clean_cache: dict[str, bool] = {}
    diagnostic_records: dict[str, int] = {}
    baseline_verifications = 0
    mutant_verifications = 0

    for injector in unique_injectors:
        metric = metrics_by_id[injector.injector_id]
        if (
            diagnostic_records.get(injector.target_diag, 0)
            >= budget.max_records_per_diagnostic
        ):
            continue
        if not injector.portable:
            rejections.append(CampaignRejection(
                status="nonportable_injector",
                reason="campaign replay accepts only portable synthesized Injectors",
                injector_id=injector.injector_id,
            ))
            continue

        injector_verification_cap = min(
            budget.max_verifications_per_injector,
            injector.limits.max_verifications,
        )
        injector_records = 0

        for source in sources:
            if source.language != injector.language:
                continue
            if metric.considered >= budget.max_sources_per_injector:
                break
            if mutant_verifications >= budget.max_verifications:
                break
            if metric.compiled >= injector_verification_cap:
                break
            if len(output) >= budget.max_records:
                break
            if injector_records >= budget.max_records_per_injector:
                break
            if (
                diagnostic_records.get(injector.target_diag, 0)
                >= budget.max_records_per_diagnostic
            ):
                break

            metric.considered += 1
            # Applicability is a pure lexical check.  Do it before the costly
            # corrected-source compile gate so campaigns can scan large real
            # corpora without recompiling TUs this Injector cannot edit.
            tokens, token_index = token_cache.get(source)
            applications = apply_injector(
                source.corrected_src,
                injector,
                max_candidates=budget.max_candidates_per_source,
                tokens=tokens,
                token_index=token_index,
            )
            if not applications:
                continue

            source_key = source.source_id
            if source_key not in clean_cache:
                baseline_verifications += 1
                try:
                    baseline = verifier.verify(
                        source.corrected_src,
                        source.compile_cmd,
                        logical_path=source.source_path,
                    )
                except Exception as error:  # keep long campaigns auditable
                    clean_cache[source_key] = False
                    rejections.append(_source_rejection(
                        "baseline_verifier_error",
                        f"corrected-source verifier raised {type(error).__name__}: {error}",
                        source,
                    ))
                else:
                    clean_cache[source_key] = baseline.ok
                    if not baseline.ok:
                        observed = baseline.diag.diag_name if baseline.diag else None
                        rejections.append(_source_rejection(
                            "corrected_not_clean",
                            "corrected_src did not compile cleanly under its recorded command",
                            source,
                            observed_diag=observed,
                        ))
            if not clean_cache[source_key]:
                continue

            metric.matched += 1
            metric.candidates += len(applications)

            for candidate_index, application in enumerate(applications):
                if mutant_verifications >= budget.max_verifications:
                    break
                if metric.compiled >= injector_verification_cap:
                    break
                if len(output) >= budget.max_records:
                    break
                if injector_records >= budget.max_records_per_injector:
                    break
                if (
                    diagnostic_records.get(injector.target_diag, 0)
                    >= budget.max_records_per_diagnostic
                ):
                    break

                mutant_verifications += 1
                metric.compiled += 1
                try:
                    verified = verifier.verify(
                        application.src,
                        source.compile_cmd,
                        logical_path=source.source_path,
                    )
                except Exception as error:  # preserve failure instead of losing a run
                    rejections.append(_candidate_rejection(
                        "candidate_verifier_error",
                        f"mutant verifier raised {type(error).__name__}: {error}",
                        injector,
                        source,
                        candidate_index,
                        application.src,
                    ))
                    continue

                if verified.ok:
                    metric.clean += 1
                    rejections.append(_candidate_rejection(
                        "candidate_clean",
                        "injected candidate still compiled cleanly",
                        injector,
                        source,
                        candidate_index,
                        application.src,
                    ))
                    continue

                if verified.diag is None or verified.diag.diag_name is None:
                    status = (
                        "candidate_timeout"
                        if "__TIMEOUT__" in verified.raw_stderr
                        else "missing_primary_diagnostic"
                    )
                    rejections.append(_candidate_rejection(
                        status,
                        "failed candidate had no typed primary diagnostic",
                        injector,
                        source,
                        candidate_index,
                        application.src,
                    ))
                    continue

                name_matches = verified.diag.diag_name == injector.target_diag
                id_matches = (
                    injector.target_diag_id is None
                    or verified.diag.diag_id == injector.target_diag_id
                )
                if not (name_matches and id_matches):
                    metric.near_miss += 1
                    rejections.append(_candidate_rejection(
                        "near_miss",
                        "primary diagnostic did not exactly match Injector target",
                        injector,
                        source,
                        candidate_index,
                        application.src,
                        observed_diag=verified.diag.diag_name,
                    ))
                    continue

                metric.exact_target += 1
                record = _make_record(
                    injector,
                    source,
                    application.src,
                    application.start,
                    application.end,
                    application.replacement,
                    replace(verified.diag, file=source.source_path),
                )
                if record.record_id in output_ids:
                    metric.duplicate_exact += 1
                    rejections.append(_candidate_rejection(
                        "duplicate_record",
                        "candidate duplicated an already accepted campaign record",
                        injector,
                        source,
                        candidate_index,
                        application.src,
                        observed_diag=verified.diag.diag_name,
                    ))
                    continue
                output_ids.add(record.record_id)
                output.append(record)
                injector_records += 1
                diagnostic_records[injector.target_diag] = (
                    diagnostic_records.get(injector.target_diag, 0) + 1
                )
                metric.records_emitted += 1
                metric.note_exact(source_key, source.project)

    return CampaignResult(
        records=tuple(output),
        rejections=tuple(rejections),
        injector_metrics=tuple(
            metrics_by_id[injector.injector_id] for injector in unique_injectors
        ),
        budget_usage={
            "baseline_verifications": baseline_verifications,
            "mutant_verifications": mutant_verifications,
            "records": len(output),
            "diagnostic_types": len(diagnostic_records),
        },
        source_pool={
            "input_records": len(source_records),
            "input_clean_sources": len(clean_sources),
            "eligible_unique_TUs": len(sources),
            "baseline_checked_unique_TUs": len(clean_cache),
            "clean_unique_TUs": sum(clean_cache.values()),
        },
    )


def _prepare_source_pool(
    records: Sequence[Record],
    rejections: list[CampaignRejection],
) -> list[_SourceTU]:
    sources: list[_SourceTU] = []
    seen: set[str] = set()
    for record in records:
        detail = record.provenance.detail
        source = record.provenance.source
        path = detail.get("source_path")
        if not isinstance(source, str) or not source:
            rejections.append(CampaignRejection(
                status="missing_provenance_source",
                reason="source Record has no stable provenance.source",
                parent_record_id=record.record_id,
            ))
            continue
        if source in seen:
            rejections.append(CampaignRejection(
                status="duplicate_source",
                reason="provenance.source already appeared in the source pool",
                parent_record_id=record.record_id,
                provenance_source=source,
                source_path=path if isinstance(path, str) else None,
            ))
            continue
        if not isinstance(path, str) or not path:
            rejections.append(CampaignRejection(
                status="missing_source_path",
                reason="provenance.detail.source_path is required",
                parent_record_id=record.record_id,
                provenance_source=source,
            ))
            continue
        if is_test_path(path) or is_test_path(source):
            rejections.append(CampaignRejection(
                status="test_source",
                reason="test/example/benchmark/fuzzer/test-support paths are forbidden",
                parent_record_id=record.record_id,
                provenance_source=source,
                source_path=path,
            ))
            continue
        if record.split is Split.AUXILIARY or not record.corrected_src:
            rejections.append(CampaignRejection(
                status="unpaired_source",
                reason="campaign source Records must be core corrected/error pairs",
                parent_record_id=record.record_id,
                provenance_source=source,
                source_path=path,
            ))
            continue
        if record.language not in ("c", "c++"):
            rejections.append(CampaignRejection(
                status="unsupported_language",
                reason="campaign supports only C and C++ source Records",
                parent_record_id=record.record_id,
                provenance_source=source,
                source_path=path,
            ))
            continue
        compile_cmd = detail.get("compile_cmd")
        if not _valid_compile_cmd(compile_cmd):
            rejections.append(CampaignRejection(
                status="invalid_compile_cmd",
                reason="compile_cmd must contain __CLANG__ and __SRC__ placeholders",
                parent_record_id=record.record_id,
                provenance_source=source,
                source_path=path,
            ))
            continue
        # Claim the stable source identity only after this row has passed all
        # source-policy validation.  An invalid earlier duplicate must not
        # suppress a later usable canonical record.
        seen.add(source)
        project = detail.get("project")
        if not isinstance(project, str) or not project:
            project = source.split(":", 1)[0]
        sources.append(_SourceTU(
            source_id=source,
            parent_record_id=record.record_id,
            corrected_src=record.corrected_src,
            compile_cmd=list(compile_cmd),
            source_path=path,
            project=project,
            language=record.language,
            split=record.split,
            provenance_detail=detail,
            source_kind="paired_record",
        ))
    return sources


def _prepare_clean_source_pool(
    clean_sources: Sequence[CleanSourceTU],
    rejections: list[CampaignRejection],
    *,
    seen: set[str],
    split: Split,
) -> list[_SourceTU]:
    """Adapt a correct-source pool without inventing a broken parent Record."""
    sources: list[_SourceTU] = []
    for clean_source in clean_sources:
        if not isinstance(clean_source, CleanSourceTU):
            raise TypeError("clean_sources must contain CleanSourceTU objects")
        if clean_source.source_id in seen:
            rejections.append(CampaignRejection(
                status="duplicate_source",
                reason="source_id already appeared in the source pool",
                provenance_source=clean_source.source_id,
                source_path=clean_source.source_path,
            ))
            continue
        if is_test_path(clean_source.source_id) or is_test_path(clean_source.source_path):
            rejections.append(CampaignRejection(
                status="test_source",
                reason="test/example/benchmark/fuzzer/test-support paths are forbidden",
                provenance_source=clean_source.source_id,
                source_path=clean_source.source_path,
            ))
            continue
        seen.add(clean_source.source_id)
        sources.append(_SourceTU(
            source_id=clean_source.source_id,
            parent_record_id=None,
            corrected_src=clean_source.corrected_src,
            compile_cmd=list(clean_source.compile_cmd),
            source_path=clean_source.source_path,
            project=clean_source.project,
            language=clean_source.language,
            split=split,
            provenance_detail={
                "project": clean_source.project,
                "source_path": clean_source.source_path,
                "compile_cmd": list(clean_source.compile_cmd),
                "clean_source_schema": "fuzzlang.clean_source_tu",
                "clean_source_schema_version": 1,
                "clean_source_baseline_compiler": clean_source.baseline_compiler,
            },
            source_kind="clean_source_tu",
            source_sha256=clean_source.source_sha256,
        ))
    return sources


def _valid_compile_cmd(value: Any) -> bool:
    return (
        isinstance(value, list)
        and all(isinstance(item, str) for item in value)
        and "__CLANG__" in value
        and "__SRC__" in value
    )


def _deduplicate_injectors(
    injectors: Sequence[FuzzLangInjector],
    rejections: list[CampaignRejection],
) -> list[FuzzLangInjector]:
    result: list[FuzzLangInjector] = []
    seen: set[str] = set()
    for injector in injectors:
        if not isinstance(injector, FuzzLangInjector):
            raise TypeError("injectors must contain FuzzLangInjector objects")
        if injector.injector_id in seen:
            rejections.append(CampaignRejection(
                status="duplicate_injector",
                reason="injector_id already appeared in campaign input",
                injector_id=injector.injector_id,
            ))
            continue
        seen.add(injector.injector_id)
        result.append(injector)
    return result


def _source_rejection(
    status: str,
    reason: str,
    source: _SourceTU,
    *,
    observed_diag: str | None = None,
) -> CampaignRejection:
    return CampaignRejection(
        status=status,
        reason=reason,
        parent_record_id=source.parent_record_id,
        provenance_source=source.source_id,
        source_path=source.source_path,
        observed_diag=observed_diag,
    )


def _candidate_rejection(
    status: str,
    reason: str,
    injector: FuzzLangInjector,
    source: _SourceTU,
    candidate_index: int,
    candidate_src: str,
    *,
    observed_diag: str | None = None,
) -> CampaignRejection:
    return CampaignRejection(
        status=status,
        reason=reason,
        injector_id=injector.injector_id,
        parent_record_id=source.parent_record_id,
        provenance_source=source.source_id,
        source_path=source.source_path,
        candidate_index=candidate_index,
        candidate_sha256=hashlib.sha256(candidate_src.encode()).hexdigest(),
        observed_diag=observed_diag,
    )


def _make_record(
    injector: FuzzLangInjector,
    source: _SourceTU,
    erroneous_src: str,
    start: int,
    end: int,
    replacement_text: str,
    diagnostic,
) -> Record:
    identity = "\0".join((
        injector.injector_id,
        source.source_id,
        erroneous_src,
    ))
    record_id = f"injector-{hashlib.sha256(identity.encode()).hexdigest()[:24]}"
    detail = dict(source.provenance_detail)
    detail.update({
        "strategy": "synthesized_injector_campaign",
        "source_pool": source.source_kind,
        "injector_schema": injector.schema,
        "injector_schema_version": injector.schema_version,
        "injector_id": injector.injector_id,
        "target_diag": injector.target_diag,
        "target_diag_id": injector.target_diag_id,
        "generation_label": "exact_target",
        "primary_matches_target": True,
        "edit": {
            "start": start,
            "end": end,
            "replacement": replacement_text,
        },
    })
    if source.parent_record_id is not None:
        detail["parent_record_id"] = source.parent_record_id
    if source.source_sha256 is not None:
        detail["source_sha256"] = source.source_sha256
    return Record(
        record_id=record_id,
        erroneous_src=erroneous_src,
        corrected_src=source.corrected_src,
        diagnostics=(diagnostic,),
        provenance=Provenance(
            origin=Origin.MUTATE,
            source=source.source_id,
            detail=detail,
        ),
        split=source.split,
        language=source.language,
    )
