"""Strict audit for diagnostic types backed by verified FuzzLang Injectors."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Iterable

from foundation.diagnostics.catalog import Catalog
from foundation.record import Record
from gen.fuzzlang_dsl.campaign import load_records_jsonl
from gen.fuzzlang_dsl.injector import FuzzLangInjector
from gen.realcorpus.corpus import is_test_path


def _load_injectors(paths: Iterable[Path]) -> list[FuzzLangInjector]:
    injectors: list[FuzzLangInjector] = []
    for path in paths:
        for line_number, line in enumerate(Path(path).read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                injectors.append(FuzzLangInjector.from_json(line))
            except ValueError as error:
                raise ValueError(
                    f"{path}:{line_number}: invalid Injector: {error}"
                ) from error
    return injectors


def _record_rejection(
    record: Record,
    injectors_by_target: dict[
        tuple[str, str], tuple[FuzzLangInjector, ...]
    ],
    injectors_by_id: dict[str, FuzzLangInjector],
    catalog_error_names: frozenset[str] | None,
) -> str | None:
    detail = record.provenance.detail
    source_path = detail.get("source_path")
    if (
        is_test_path(record.provenance.source)
        or not isinstance(source_path, str)
        or is_test_path(source_path)
    ):
        return "test_or_test_support_source"
    if (
        not record.is_core
        or not record.corrected_src
        or record.corrected_src == record.erroneous_src
    ):
        return "missing_or_unchanged_corrected_pair"
    target = detail.get("target_diag")
    primary = record.primary_diagnostic
    if (
        not isinstance(target, str)
        or not target
        or primary is None
        or primary.diag_name != target
        or detail.get("primary_matches_target") is not True
    ):
        return "primary_target_mismatch"
    if catalog_error_names is not None and target not in catalog_error_names:
        return "target_not_catalog_error_diagnostic"
    # New witness generation writes the concrete replayed Injector ID into
    # provenance.  Its audit must not be satisfied by an unrelated Injector
    # which happens to share the same diagnostic name.
    if detail.get("strategy") == "gemma_code_witness_injector_replay":
        injector_id = detail.get("injector_id")
        injector = (
            injectors_by_id.get(injector_id)
            if isinstance(injector_id, str)
            else None
        )
        if (
            injector is None
            or injector.target_diag != target
            or injector.language != record.language
            or (
                injector.target_diag_id is not None
                and injector.target_diag_id != primary.diag_id
            )
        ):
            return "recorded_injector_missing_or_mismatched"
        return None
    candidates = injectors_by_target.get((target, record.language), ())
    if not candidates:
        return "missing_portable_injector"
    if not any(
        injector.target_diag_id is None
        or injector.target_diag_id == primary.diag_id
        for injector in candidates
    ):
        return "injector_diag_id_mismatch"
    return None


def audit_verified_injector_coverage(
    injector_paths: Iterable[Path],
    record_paths: Iterable[Path],
    *,
    catalog: Catalog | None = None,
) -> dict:
    """Audit exact typed-diagnostic breadth with all core data gates applied."""
    injector_paths = tuple(Path(path) for path in injector_paths)
    record_paths = tuple(Path(path) for path in record_paths)
    if not injector_paths or not record_paths:
        raise ValueError("audit requires Injector and Record JSONL inputs")

    input_injectors = _load_injectors(injector_paths)
    injectors_by_id = {
        injector.injector_id: injector
        for injector in input_injectors
        if injector.portable
    }
    grouped: dict[tuple[str, str], list[FuzzLangInjector]] = {}
    for injector in injectors_by_id.values():
        grouped.setdefault(
            (injector.target_diag, injector.language), []
        ).append(injector)
    injectors_by_target = {
        key: tuple(values) for key, values in grouped.items()
    }
    catalog_error_names = (
        frozenset(entry.name for entry in catalog.entries if entry.is_error)
        if catalog is not None else None
    )

    records = [
        record
        for path in record_paths
        for record in load_records_jsonl(path)
    ]
    rejections: Counter[str] = Counter()
    strict_records: dict[str, Record] = {}
    verified_names: set[str] = set()
    replay_names: set[str] = set()
    for record in records:
        reason = _record_rejection(
            record, injectors_by_target, injectors_by_id, catalog_error_names,
        )
        if reason is not None:
            rejections[reason] += 1
            continue
        strict_records.setdefault(record.record_id, record)
        target = record.provenance.detail["target_diag"]
        verified_names.add(target)
        injector_id = record.provenance.detail.get("injector_id")
        if (
            record.provenance.detail.get("strategy")
            == "synthesized_injector_campaign"
            and isinstance(injector_id, str)
            and injector_id in injectors_by_id
        ):
            replay_names.add(target)

    injector_names = {
        injector.target_diag for injector in injectors_by_id.values()
    }
    return {
        "schema": "fuzzlang.verified_injector_coverage_audit.v1",
        "inputs": {
            "injector_files": [str(path) for path in injector_paths],
            "record_files": [str(path) for path in record_paths],
        },
        "counts": {
            "input_injector_rows": len(input_injectors),
            "unique_portable_injectors": len(injectors_by_id),
            "injector_diagnostic_types": len(injector_names),
            "input_record_rows": len(records),
            "strict_verified_records": len(strict_records),
            "verified_diagnostic_types": len(verified_names),
            "cross_source_replay_diagnostic_types": len(replay_names),
            **(
                {"catalog_error_diagnostic_total": len(catalog_error_names)}
                if catalog_error_names is not None else {}
            ),
        },
        "verified_diagnostic_names": sorted(verified_names),
        "cross_source_replay_diagnostic_names": sorted(replay_names),
        "rejections": dict(sorted(rejections.items())),
    }
