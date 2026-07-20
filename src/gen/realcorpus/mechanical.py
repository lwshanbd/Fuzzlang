"""Bounded mechanical mutation over correct source recovered from RealSource.

This module consumes canonical paired Records only as a source of clean code and
its real compile command.  It never trusts that code blindly: the corrected
translation unit is compiled before any bounded mechanical candidate is kept.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, replace
from typing import Iterable, Optional, Sequence

from foundation.record import Origin, Provenance, Record
from foundation.verifier.base import BaseVerifier
from gen.mutate import text_mutations
from gen.mutate.base import BaseMutation, Mutant
from gen.realcorpus.corpus import is_test_path


@dataclass(frozen=True)
class MechanicalRejection:
    status: str
    parent_record_id: str
    source: str
    source_path: Optional[str]
    mutation: Optional[str] = None
    description: Optional[str] = None
    mutant_hash: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "parent_record_id": self.parent_record_id,
            "source": self.source,
            "source_path": self.source_path,
            "mutation": self.mutation,
            "description": self.description,
            "mutant_hash": self.mutant_hash,
        }


@dataclass(frozen=True)
class SourceSelection:
    records: tuple[Record, ...]
    rejections: tuple[MechanicalRejection, ...]

    @property
    def statuses(self) -> dict[str, int]:
        counts = Counter(rejection.status for rejection in self.rejections)
        counts["selected"] = len(self.records)
        return dict(counts)


@dataclass(frozen=True)
class MechanicalOutcome:
    status: str
    records: tuple[Record, ...] = ()
    rejections: tuple[MechanicalRejection, ...] = ()
    baseline_compiles: int = 0
    mutant_compiles: int = 0
    candidates_selected: int = 0


def _source_path(record: Record) -> Optional[str]:
    value = record.provenance.detail.get("source_path")
    return value if isinstance(value, str) and value else None


def _validation_status(record: Record) -> Optional[str]:
    source_path = _source_path(record)
    if source_path is None:
        return "missing_source_path"
    if is_test_path(source_path) or is_test_path(record.provenance.source):
        return "test_source"
    if not record.corrected_src:
        return "missing_corrected_src"
    compile_cmd = record.provenance.detail.get("compile_cmd")
    if (
        not isinstance(compile_cmd, list)
        or "__CLANG__" not in compile_cmd
        or "__SRC__" not in compile_cmd
    ):
        return "invalid_compile_cmd"
    if record.language not in ("c", "c++"):
        return "unsupported_language"
    return None


def _rejection(
    status: str,
    record: Record,
    *,
    mutation: Optional[BaseMutation] = None,
    mutant: Optional[Mutant] = None,
) -> MechanicalRejection:
    return MechanicalRejection(
        status=status,
        parent_record_id=record.record_id,
        source=record.provenance.source,
        source_path=_source_path(record),
        mutation=mutation.name if mutation else None,
        description=mutant.description if mutant else None,
        mutant_hash=(
            hashlib.sha256(mutant.src.encode("utf-8")).hexdigest()
            if mutant else None
        ),
    )


def select_real_source_records(records: Iterable[Record]) -> SourceSelection:
    """Validate and choose one deterministic parent per provenance source."""
    selected: list[Record] = []
    rejections: list[MechanicalRejection] = []
    seen_sources: set[str] = set()
    for record in sorted(
        records, key=lambda value: (value.provenance.source, value.record_id)
    ):
        invalid = _validation_status(record)
        if invalid is not None:
            rejections.append(_rejection(invalid, record))
            continue
        if record.provenance.source in seen_sources:
            rejections.append(_rejection("duplicate_source", record))
            continue
        seen_sources.add(record.provenance.source)
        selected.append(record)
    return SourceSelection(tuple(selected), tuple(rejections))


def _record_id(
    source: str, mutation: str, description: str, erroneous_src: str,
) -> str:
    payload = f"{source}|{mutation}|{description}|{erroneous_src}".encode("utf-8")
    return "mechanical-real-" + hashlib.sha256(payload).hexdigest()[:16]


def mutate_real_source(
    parent: Record,
    verifier: BaseVerifier,
    *,
    mutations: Optional[Sequence[BaseMutation]] = None,
    seed: int,
    max_candidates_per_mutation: int,
    max_verifications: int,
    max_records: int,
) -> MechanicalOutcome:
    """Clean-gate one source, sample bounded mutants, and verify canonical pairs."""
    invalid = _validation_status(parent)
    if invalid is not None:
        return MechanicalOutcome(
            invalid,
            rejections=(_rejection(invalid, parent),),
        )
    if max_records <= 0:
        return MechanicalOutcome("record_cap_zero")
    if mutations is None:
        mutations = text_mutations()

    source_path = _source_path(parent)
    assert source_path is not None
    compile_cmd = list(parent.provenance.detail["compile_cmd"])
    correct_src = parent.corrected_src
    assert correct_src is not None
    baseline = verifier.verify(
        correct_src, compile_cmd, logical_path=source_path
    )
    if not baseline.ok:
        return MechanicalOutcome(
            "corrected_not_clean",
            rejections=(_rejection("corrected_not_clean", parent),),
            baseline_compiles=1,
        )

    records: list[Record] = []
    rejections: list[MechanicalRejection] = []
    actual_diags: set[str] = set()
    mutant_compiles = 0
    candidates_selected = 0
    verification_capped = False

    for mutation in mutations:
        candidates = mutation.bounded_mutants(
            correct_src,
            max_candidates=max_candidates_per_mutation,
            seed=seed,
        )
        candidates_selected += len(candidates)
        for mutant in candidates:
            if mutant_compiles >= max_verifications:
                rejections.append(_rejection(
                    "verification_cap", parent,
                    mutation=mutation, mutant=mutant,
                ))
                verification_capped = True
                break
            result = verifier.verify(
                mutant.src, compile_cmd, logical_path=source_path
            )
            mutant_compiles += 1
            if result.ok:
                rejections.append(_rejection(
                    "mutant_clean", parent, mutation=mutation, mutant=mutant
                ))
                continue
            if result.diag is None or not result.diag.diag_name:
                status = (
                    "timeout" if "__TIMEOUT__" in result.raw_stderr
                    else "missing_primary_diagnostic"
                )
                rejections.append(_rejection(
                    status, parent, mutation=mutation, mutant=mutant
                ))
                continue
            if result.diag.diag_name in actual_diags:
                rejections.append(_rejection(
                    "duplicate_diagnostic_source", parent,
                    mutation=mutation, mutant=mutant,
                ))
                continue
            actual_diags.add(result.diag.diag_name)
            diag = replace(result.diag, file=source_path)
            records.append(Record(
                record_id=_record_id(
                    parent.provenance.source,
                    mutation.name,
                    mutant.description,
                    mutant.src,
                ),
                erroneous_src=mutant.src,
                corrected_src=correct_src,
                diagnostics=(diag,),
                provenance=Provenance(
                    origin=Origin.MUTATE,
                    source=parent.provenance.source,
                    detail={
                        "strategy": "mechanical_real_source",
                        "mutation": mutation.name,
                        "description": mutant.description,
                        "expected_diag": mutant.expected_diag,
                        "compile_cmd": compile_cmd,
                        "source_path": source_path,
                        "seed": seed,
                        "parent_record_id": parent.record_id,
                    },
                ),
                split=parent.split,
                language=parent.language,
            ))
            if len(records) >= max_records:
                break
        if verification_capped or len(records) >= max_records:
            break

    if records:
        status = "accepted"
    elif verification_capped:
        status = "verification_cap"
    elif candidates_selected == 0:
        status = "no_candidates"
    else:
        status = "no_verified_mutants"
    return MechanicalOutcome(
        status=status,
        records=tuple(records),
        rejections=tuple(rejections),
        baseline_compiles=1,
        mutant_compiles=mutant_compiles,
        candidates_selected=candidates_selected,
    )
