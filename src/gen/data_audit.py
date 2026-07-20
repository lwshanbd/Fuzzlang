"""Streaming audit of the three frozen FuzzLang data tiers.

The audit deliberately consumes raw JSON objects rather than constructing
``Record`` instances.  That lets it report legacy or invalid release rows --
especially NatErr rows that do not yet have ``corrected_src`` -- instead of
failing at the canonical schema's core-pair invariant.
"""
from __future__ import annotations

import json
from collections import Counter
from itertools import combinations
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from gen.realcorpus.corpus import is_test_path


TIER_NAMES = ("breadth", "real_source", "naterr")


def _nonempty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _schema_name(row: dict) -> str:
    if (
        "record_id" in row
        and "erroneous_src" in row
        and "diagnostics" in row
        and "provenance" in row
    ):
        return "canonical_record"
    if "buggy_src" in row and "source_file" in row and "project" in row:
        return "legacy_naterr"
    if "buggy_src" in row or "erroneous_src" in row:
        return "flat_record"
    return "unknown"


def _diagnostic_names(row: dict) -> set[str]:
    names: set[str] = set()
    diagnostics = row.get("diagnostics")
    if isinstance(diagnostics, list):
        for diagnostic in diagnostics:
            if not isinstance(diagnostic, dict):
                continue
            name = diagnostic.get("diag_name")
            if _nonempty_text(name):
                names.add(name)
    direct_name = row.get("diag_name")
    if _nonempty_text(direct_name):
        names.add(direct_name)
    return names


def _provenance(row: dict) -> tuple[str | None, str | None]:
    """Return ``(stable source identity, auditable filesystem-like path)``."""
    provenance = row.get("provenance")
    if isinstance(provenance, dict):
        source = provenance.get("source")
        detail = provenance.get("detail")
        source_path = detail.get("source_path") if isinstance(detail, dict) else None
        stable_source = source if _nonempty_text(source) else None
        if not _nonempty_text(source_path) and stable_source:
            # Canonical RealSource identities are normally ``project:path``.
            # The suffix is useful for the path filter, while the full value is
            # retained as the overlap identity.
            source_path = stable_source.split(":", 1)[-1]
        return stable_source, source_path if _nonempty_text(source_path) else None

    source_path = row.get("source_path") or row.get("source_file")
    project = row.get("project")
    if _nonempty_text(source_path):
        normalized_path = source_path.replace("\\", "/")
        if _nonempty_text(project):
            return f"{project}:{normalized_path}", normalized_path
        return normalized_path, normalized_path

    source = row.get("source")
    if _nonempty_text(source):
        return source, source.split(":", 1)[-1]
    return None, None


class _TierAudit:
    def __init__(self, paths: Sequence[Path]) -> None:
        self.paths = paths
        self.records = 0
        self.paired_records = 0
        self.missing_corrected_src = 0
        self.missing_erroneous_src = 0
        self.diagnostics: set[str] = set()
        self.sources: set[str] = set()
        self.source_inputs: dict[str, set[str]] = {}
        self.missing_source = 0
        self.test_sources = 0
        self.test_source_paths: set[str] = set()
        self.schema_counts: Counter[str] = Counter()
        self.invalid_json_rows = 0
        self.non_object_rows = 0

    def consume(self, row: dict, *, input_path: Path) -> None:
        self.records += 1
        self.schema_counts[_schema_name(row)] += 1

        erroneous = row.get("erroneous_src", row.get("buggy_src"))
        corrected = row.get("corrected_src")
        has_erroneous = _nonempty_text(erroneous)
        has_corrected = _nonempty_text(corrected)
        if not has_erroneous:
            self.missing_erroneous_src += 1
        if not has_corrected:
            self.missing_corrected_src += 1
        if has_erroneous and has_corrected:
            self.paired_records += 1

        self.diagnostics.update(_diagnostic_names(row))
        source, source_path = _provenance(row)
        if source is None:
            self.missing_source += 1
        else:
            self.sources.add(source)
            self.source_inputs.setdefault(source, set()).add(str(input_path))
        if source_path is not None and is_test_path(source_path):
            self.test_sources += 1
            self.test_source_paths.add(source_path)

    def result(self) -> dict:
        return {
            "input_files": [str(path) for path in self.paths],
            "records": self.records,
            "paired_records": self.paired_records,
            "missing_corrected_src": self.missing_corrected_src,
            "missing_erroneous_src": self.missing_erroneous_src,
            "distinct_diagnostics": len(self.diagnostics),
            "diagnostic_names": sorted(self.diagnostics),
            "unique_sources": len(self.sources),
            "missing_source": self.missing_source,
            "test_sources": self.test_sources,
            "test_source_paths": sorted(self.test_source_paths),
            "schema_counts": dict(sorted(self.schema_counts.items())),
            "invalid_json_rows": self.invalid_json_rows,
            "non_object_rows": self.non_object_rows,
        }

    def input_overlap(self) -> dict:
        shared = sorted(
            source for source, paths in self.source_inputs.items() if len(paths) > 1
        )
        return {"count": len(shared), "sources": shared}


def _consume_paths(paths: Sequence[Path]) -> _TierAudit:
    audit = _TierAudit(paths)
    for path in paths:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    audit.invalid_json_rows += 1
                    continue
                if not isinstance(row, dict):
                    audit.non_object_rows += 1
                    continue
                audit.consume(row, input_path=path)
    return audit


def audit_tiers(inputs: Mapping[str, Iterable[Path]]) -> dict:
    """Audit explicit JSONL inputs without loading source bodies into memory.

    Only distinct diagnostic names and source identities are retained while
    streaming.  Those sets are required for exact breadth and overlap counts;
    full records and source texts are never retained.
    """
    actual_names = set(inputs)
    expected_names = set(TIER_NAMES)
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        extra = sorted(actual_names - expected_names)
        raise ValueError(f"tier inputs must match {TIER_NAMES}; missing={missing}, extra={extra}")

    audits: dict[str, _TierAudit] = {}
    for tier in TIER_NAMES:
        paths = tuple(Path(path) for path in inputs[tier])
        if not paths:
            raise ValueError(f"tier {tier!r} requires at least one input path")
        audits[tier] = _consume_paths(paths)

    overlaps = {}
    for left, right in combinations(TIER_NAMES, 2):
        shared = sorted(audits[left].sources & audits[right].sources)
        overlaps[f"{left}__{right}"] = {"count": len(shared), "sources": shared}

    return {
        "schema_version": 1,
        "tiers": {tier: audits[tier].result() for tier in TIER_NAMES},
        "source_overlap": overlaps,
        "within_tier_source_overlap": {
            tier: audits[tier].input_overlap() for tier in TIER_NAMES
        },
    }
