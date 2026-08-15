"""Freeze verified records into a citable dataset release.

A paper about a dataset needs the dataset to be a *thing*: one directory, one
manifest, checksums, and splits that cannot move. Until then the records live in
an experiment directory and every number in the paper points at a path that was
never promised to stay put.

The gates below are the ones the paper claims, restated as code. They run at
freeze time over every record, and a release with any violation is refused
rather than published with a footnote.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping, Sequence

from gen.realcorpus.corpus import is_test_path, is_vendored_path

#: Every gate the release manifest advertises. Each name has a check below.
RELEASE_INVARIANTS = (
    "corrected_src_present",
    "corrected_differs",
    "no_test_source",
    "no_vendored_source",
    "target_not_relabelled",
    "primary_matches_target",
    "injector_recorded",
    "unique_record_id",
)

SPLITS = ("train", "eval_unseen_tu", "heldout_project")


def _detail(record: Mapping[str, Any]) -> Mapping[str, Any]:
    return (record.get("provenance") or {}).get("detail") or {}


def verify_invariants(
    records: Iterable[Mapping[str, Any]],
) -> dict[str, list[str]]:
    """Record IDs that break each gate, keyed by gate name.

    An empty mapping means the set is releasable. Gates that pass do not appear,
    so the result reads as a list of problems rather than a checklist.
    """
    violations: dict[str, list[str]] = defaultdict(list)
    seen: set[str] = set()
    for record in records:
        record_id = str(record.get("record_id") or "")
        detail = _detail(record)
        source_path = str(detail.get("source_path") or "")
        erroneous = record.get("erroneous_src") or ""
        corrected = record.get("corrected_src") or ""
        diagnostics = record.get("diagnostics") or []
        primary = diagnostics[0] if diagnostics else {}

        if not corrected:
            violations["corrected_src_present"].append(record_id)
        elif corrected == erroneous:
            violations["corrected_differs"].append(record_id)
        if is_test_path(source_path):
            violations["no_test_source"].append(record_id)
        if is_vendored_path(source_path):
            violations["no_vendored_source"].append(record_id)
        if detail.get("opportunistic_observed_diagnostic"):
            violations["target_not_relabelled"].append(record_id)
        if primary.get("diag_name") != detail.get("target_diag"):
            violations["primary_matches_target"].append(record_id)
        if not detail.get("injector_id"):
            violations["injector_recorded"].append(record_id)
        if record_id in seen:
            violations["unique_record_id"].append(record_id)
        seen.add(record_id)
    return dict(violations)


def split_records(
    records: Iterable[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group records by the split frozen *before* generation.

    The assignment lives in ``provenance.detail.source_split`` and is derived
    from a fixed hash of the source, so it never moves as the pool grows.
    Grouping by the file a record arrived in would instead trust the run that
    produced it, and a mis-filed record would cross the train/eval boundary
    without anything noticing.
    """
    grouped: dict[str, list[dict[str, Any]]] = {split: [] for split in SPLITS}
    for record in records:
        split = str(_detail(record).get("source_split") or "")
        if split not in grouped:
            raise ValueError(
                f"record {record.get('record_id')!r} has unknown "
                f"source_split {split!r}; expected one of {SPLITS}"
            )
        copied = dict(record)
        copied["split"] = split
        grouped[split].append(copied)
    return grouped


def split_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Counts a manifest quotes for one split."""
    diagnostics = {str(_detail(r).get("target_diag")) for r in records}
    multiplicity: dict[str, int] = defaultdict(int)
    for record in records:
        multiplicity[str(_detail(record).get("target_diag"))] += 1
    projects: dict[str, int] = defaultdict(int)
    languages: dict[str, int] = defaultdict(int)
    for record in records:
        projects[str(_detail(record).get("project") or "?")] += 1
        languages[str(record.get("language") or "?")] += 1
    return {
        "records": len(records),
        "diagnostics": len(diagnostics),
        "diagnostics_at_multiplicity_3": sum(
            1 for count in multiplicity.values() if count >= 3
        ),
        "source_files": len({str(_detail(r).get("source_path")) for r in records}),
        "injectors": len({str(_detail(r).get("injector_id")) for r in records}),
        "projects": dict(sorted(projects.items())),
        "languages": dict(sorted(languages.items())),
    }
