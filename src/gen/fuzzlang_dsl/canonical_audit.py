"""One reproducible union audit of strictly verified Injector coverage.

Earlier release audits each enumerated their own campaign subset, so two
audits of the same project state could disagree on both the numerator and the
inputs that produced it.  This module freezes a single explicit input list,
applies exactly the gate in :mod:`gen.fuzzlang_dsl.coverage_audit`, and emits
the diagnostic-to-record mapping a release manifest needs:

* a Record counts only with a clean non-test parent, a ``corrected_src``, a
  portable Injector recorded in its provenance, and a primary typed diagnostic
  equal to the requested target;
* candidates, unreplayed Injectors, and Clang regression-test sources are never
  part of the numerator;
* every input file is checksummed so the audit can be recomputed and compared.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from foundation.diagnostics.catalog import Catalog
from gen.fuzzlang_dsl.coverage_audit import (
    RecordEvaluation, evaluate_records, index_injectors, paper_scope_names,
)

SCHEMA = "fuzzlang.canonical_strict_injector_audit.v1"


@dataclass(frozen=True)
class AuditInput:
    """One campaign's portable Injector file and its verified Record file."""

    label: str
    injector_path: Path
    record_path: Path

    def __post_init__(self) -> None:
        if not self.label:
            raise ValueError("an audit input needs a campaign label")
        object.__setattr__(self, "injector_path", Path(self.injector_path))
        object.__setattr__(self, "record_path", Path(self.record_path))


def _digest(path: Path) -> tuple[str, int, int]:
    payload = path.read_bytes()
    rows = sum(1 for line in payload.decode().splitlines() if line.strip())
    return hashlib.sha256(payload).hexdigest(), len(payload), rows


def _ordered_unique(paths: Iterable[Path]) -> tuple[list[Path], list[str]]:
    seen: dict[str, Path] = {}
    duplicates: list[str] = []
    for path in paths:
        key = str(path)
        if key in seen:
            duplicates.append(key)
            continue
        seen[key] = path
    return list(seen.values()), sorted(set(duplicates))


def build_canonical_audit(
    inputs: Sequence[AuditInput],
    *,
    catalog: Catalog,
    out_of_scope: Iterable[str],
    base_verified_names: Iterable[str],
    base_label: str,
    exclude_opportunistic: bool = True,
) -> dict:
    """Audit the frozen union of ``inputs`` and index it by diagnostic.

    ``exclude_opportunistic`` drops records whose ``target_diag`` was relabelled
    to whatever diagnostic the mutation happened to emit.  Such a record is
    still a verified pair, but it is not evidence that the requested gap was
    reached, so the goal-directed numerator must not include it.
    """
    if not inputs:
        raise ValueError("a canonical audit needs at least one campaign input")
    missing = [
        str(path)
        for item in inputs
        for path in (item.injector_path, item.record_path)
        if not path.is_file()
    ]
    if missing:
        raise FileNotFoundError(f"audit inputs do not exist: {missing}")

    injector_paths, injector_duplicates = _ordered_unique(
        item.injector_path for item in inputs
    )
    record_paths, record_duplicates = _ordered_unique(
        item.record_path for item in inputs
    )
    labels: dict[str, str] = {}
    for item in inputs:
        labels.setdefault(str(item.record_path), item.label)

    index = index_injectors(injector_paths)
    catalog_error_names = frozenset(
        entry.name for entry in catalog.entries if entry.is_error
    )
    paper_names = paper_scope_names(catalog, out_of_scope)
    components = {entry.name: entry.component for entry in catalog.errors()}

    admitted: dict[str, RecordEvaluation] = {}
    rejections: dict[str, int] = defaultdict(int)
    replay_names: set[str] = set()
    input_record_rows = 0
    for evaluation in evaluate_records(
        record_paths, index, catalog_error_names=catalog_error_names,
    ):
        input_record_rows += 1
        if evaluation.rejection is not None:
            rejections[evaluation.rejection] += 1
            continue
        if exclude_opportunistic and evaluation.record.provenance.detail.get(
            "opportunistic_observed_diagnostic"
        ) is True:
            rejections["opportunistic_relabelled_target"] += 1
            continue
        admitted.setdefault(evaluation.record.record_id, evaluation)
        if evaluation.is_cross_source_replay:
            replay_names.add(evaluation.record.provenance.detail["target_diag"])

    diagnostic_index = _index_by_diagnostic(
        admitted.values(), paper_names=paper_names, components=components,
        labels=labels,
    )
    verified_names = set(diagnostic_index)
    base_names = frozenset(base_verified_names)

    return {
        "schema": SCHEMA,
        "base_audit_label": base_label,
        "counts": {
            "catalog_error_diagnostic_total": len(catalog_error_names),
            "input_injector_rows": index.input_rows,
            "unique_portable_injectors": len(index.by_id),
            "injector_diagnostic_types": len(index.diagnostic_names),
            "input_record_rows": input_record_rows,
            "strict_verified_records": len(admitted),
            "verified_diagnostic_types": len(verified_names),
            "cross_source_replay_diagnostic_types": len(replay_names),
        },
        "paper_scope": {
            "total_diagnostic_types": len(paper_names),
            "verified_diagnostic_types": len(paper_names & verified_names),
            "new_vs_base_diagnostic_names": sorted(
                paper_names & (verified_names - base_names)
            ),
        },
        "verified_diagnostic_names": sorted(verified_names),
        "cross_source_replay_diagnostic_names": sorted(replay_names),
        "excludes_opportunistic_relabelled_targets": exclude_opportunistic,
        "rejections": dict(sorted(rejections.items())),
        "diagnostic_index": diagnostic_index,
        "input_manifest": _input_manifest(inputs),
        "duplicate_input_paths": sorted(set(injector_duplicates + record_duplicates)),
        "record_file_labels": labels,
    }


def _index_by_diagnostic(
    admitted: Iterable[RecordEvaluation],
    *,
    paper_names: frozenset[str],
    components: dict[str, str | None],
    labels: dict[str, str],
) -> dict[str, dict]:
    grouped: dict[str, dict[str, set]] = defaultdict(
        lambda: {
            "record_ids": set(), "injector_ids": set(), "campaigns": set(),
            "projects": set(), "source_tus": set(), "languages": set(),
            "strategies": set(),
        }
    )
    for evaluation in admitted:
        record = evaluation.record
        detail = record.provenance.detail
        bucket = grouped[detail["target_diag"]]
        bucket["record_ids"].add(record.record_id)
        bucket["campaigns"].add(labels[str(evaluation.record_path)])
        bucket["source_tus"].add(record.provenance.source)
        bucket["languages"].add(record.language)
        for key, field in (
            ("injector_id", "injector_ids"),
            ("project", "projects"),
            ("strategy", "strategies"),
        ):
            value = detail.get(key)
            if isinstance(value, str) and value:
                bucket[field].add(value)
    return {
        name: {
            "component": components.get(name) or "Unknown",
            "in_paper_scope": name in paper_names,
            "strict_records": len(bucket["record_ids"]),
            "source_tus": len(bucket["source_tus"]),
            "injector_ids": sorted(bucket["injector_ids"]),
            "campaigns": sorted(bucket["campaigns"]),
            "projects": sorted(bucket["projects"]),
            "languages": sorted(bucket["languages"]),
            "strategies": sorted(bucket["strategies"]),
        }
        for name, bucket in sorted(grouped.items())
    }


def _input_manifest(inputs: Sequence[AuditInput]) -> list[dict]:
    """Checksum every distinct input file once, keeping its first label."""
    manifest: list[dict] = []
    seen: set[str] = set()
    for item in inputs:
        for kind, path in (
            ("injectors", item.injector_path), ("records", item.record_path),
        ):
            if str(path) in seen:
                continue
            seen.add(str(path))
            sha256, size, rows = _digest(path)
            manifest.append({
                "label": item.label, "kind": kind, "path": str(path),
                "sha256": sha256, "bytes": size, "rows": rows,
            })
    return manifest


def diagnostic_record_rows(audit: dict) -> list[dict[str, str]]:
    """Flatten the diagnostic index into CSV-ready release-manifest rows."""
    new_names = set(audit["paper_scope"]["new_vs_base_diagnostic_names"])
    rows: list[dict[str, str]] = []
    for name, entry in audit["diagnostic_index"].items():
        rows.append({
            "diag_name": name,
            "component": entry["component"],
            "in_paper_scope": str(entry["in_paper_scope"]).lower(),
            "new_vs_base": str(name in new_names).lower(),
            "strict_records": str(entry["strict_records"]),
            "source_tus": str(entry["source_tus"]),
            "injector_count": str(len(entry["injector_ids"])),
            "languages": "|".join(entry["languages"]),
            "projects": "|".join(entry["projects"]),
            "strategies": "|".join(entry["strategies"]),
            "campaign_count": str(len(entry["campaigns"])),
            "injector_ids": "|".join(entry["injector_ids"]),
        })
    return rows


def replaced_campaign_labels(audit: dict) -> dict[str, str]:
    """Map each admitted campaign record file back to its declared label."""
    return dict(audit["record_file_labels"])
