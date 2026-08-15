#!/usr/bin/env python3
"""Freeze one canonical strict Injector coverage audit and its inventory.

Every earlier release audit enumerated its own campaign subset, so `batch0053`
and the later live audit disagreed on both the numerator and the inputs.  This
script takes the *union* of the pinned batch-6 base inputs and every completed
post-batch-6 campaign listed in :data:`POST_BASE_CAMPAIGNS`, checksums each
input file, and writes the diagnostic-to-record mapping a release manifest
needs.

Two numerators are always reported from exactly the same inputs:

``strict``
    the headline.  A record counts only when the compiler emitted the
    diagnostic that was actually *requested*.
``inclusive``
    the same audit with opportunistically relabelled targets kept, published
    only so the difference is visible rather than silently chosen.

Neither counts candidates, unreplayed Injectors, or Clang regression-test
sources: those are rejected by the shared gate in
:mod:`gen.fuzzlang_dsl.coverage_audit`.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from foundation.diagnostics.catalog import load_catalog
from gen.fuzzlang_dsl.canonical_audit import (
    AuditInput, build_canonical_audit, diagnostic_record_rows,
)
from gen.fuzzlang_dsl.coverage_audit import paper_scope_names

EXPERIMENTS = Path("data/gen/experiments")
GAP_ROOT = EXPERIMENTS / "clang-test-gap-injector-v0002"
DEFAULT_BASE = GAP_ROOT / "strict-injector-coverage-audit-batch0006.json"
DEFAULT_OUT_OF_SCOPE = Path("data/gen/out_of_scope.txt")

# Completed post-batch-6 campaigns, enumerated rather than globbed.  Each entry
# is (label, injector file, record file) relative to GAP_ROOT.  A campaign that
# emitted both a same-source witness file and a separate cross-source replay
# file appears twice: both are compiler-verified paired records, and dropping
# either was the main cause of the batch0053/live disagreement.
POST_BASE_CAMPAIGNS: tuple[tuple[str, str, str], ...] = (
    ("B33 C++23 breadth (witness)", "paper-scope-cpp23-breadth-batch-0033/gemma-run/injectors.jsonl", "paper-scope-cpp23-breadth-batch-0033/gemma-run/records.jsonl"),
    ("B33 C++23 breadth (replay)", "paper-scope-cpp23-breadth-batch-0033/gemma-run/injectors.jsonl", "paper-scope-cpp23-breadth-batch-0033/replay/records.jsonl"),
    ("B34 C++23 emission (witness)", "paper-scope-cpp23-emission-batch-0034/gemma-run/injectors.jsonl", "paper-scope-cpp23-emission-batch-0034/gemma-run/records.jsonl"),
    ("B34 C++23 emission (replay)", "paper-scope-cpp23-emission-batch-0034/gemma-run/injectors.jsonl", "paper-scope-cpp23-emission-batch-0034/replay/records.jsonl"),
    ("B36 preprocessor (witness)", "paper-scope-preprocessor-test-batch-0036/gemma-run/injectors.jsonl", "paper-scope-preprocessor-test-batch-0036/gemma-run/records.jsonl"),
    ("B36 preprocessor (replay)", "paper-scope-preprocessor-test-batch-0036/gemma-run/injectors.jsonl", "paper-scope-preprocessor-test-batch-0036/replay/records.jsonl"),
    ("B37 C++23 emission tail (witness)", "paper-scope-cpp23-emission-tail-batch-0037/gemma-run/injectors.jsonl", "paper-scope-cpp23-emission-tail-batch-0037/gemma-run/records.jsonl"),
    ("B49 C11 (witness)", "paper-scope-c11-test-fastlane-batch-0049/gemma-run/injectors.jsonl", "paper-scope-c11-test-fastlane-batch-0049/gemma-run/records.jsonl"),
    ("B49 C11 (replay)", "paper-scope-c11-test-fastlane-batch-0049/gemma-run/injectors.jsonl", "paper-scope-c11-test-fastlane-batch-0049/replay/records.jsonl"),
    ("B62 C++23 emission tail (witness)", "strict-target-cpp23-emission-batch-0062/gemma-run/injectors.jsonl", "strict-target-cpp23-emission-batch-0062/gemma-run/records.jsonl"),
    ("B63 Abseil C++23 (witness)", "strict-target-abseil-cpp23-test-batch-0063/gemma-run/injectors.jsonl", "strict-target-abseil-cpp23-test-batch-0063/gemma-run/records.jsonl"),
)


def _label_for(path: Path) -> str:
    """Attribute a base-audit input to its campaign directory."""
    try:
        return str(path.parent.relative_to(EXPERIMENTS))
    except ValueError:
        return str(path.parent)


def collect_inputs(
    base_audit: Path,
) -> tuple[list[AuditInput], list[AuditInput], list[str], list[str]]:
    """Pair base and post-base input files into labelled audit inputs.

    Returns the base inputs, the post-batch-6 campaign inputs, any input path
    that does not exist, and any declared campaign that has not produced both
    files yet (an unfinished campaign is skipped, never partially counted).
    """
    base = json.loads(base_audit.read_text())
    injector_files = [Path(path) for path in base["inputs"]["injector_files"]]
    record_files = [Path(path) for path in base["inputs"]["record_files"]]
    if not injector_files or not record_files:
        raise ValueError(f"{base_audit} declares no audit inputs")

    # The base audit stores two flat file lists rather than campaign pairs.
    # Pairing by position only affects the human-readable label; the audit
    # itself consumes the deduplicated union of both lists.
    base_inputs = [
        AuditInput(
            label=_label_for(record),
            injector_path=injector_files[min(number, len(injector_files) - 1)],
            record_path=record,
        )
        for number, record in enumerate(record_files)
    ]
    paired = {str(item.injector_path) for item in base_inputs}
    base_inputs.extend(
        AuditInput(
            label=_label_for(injector),
            injector_path=injector,
            record_path=record_files[0],
        )
        for injector in injector_files if str(injector) not in paired
    )

    post_inputs: list[AuditInput] = []
    incomplete: list[str] = []
    for label, injector, record in POST_BASE_CAMPAIGNS:
        injector_path, record_path = GAP_ROOT / injector, GAP_ROOT / record
        if injector_path.is_file() and record_path.is_file():
            post_inputs.append(AuditInput(
                label=label, injector_path=injector_path, record_path=record_path,
            ))
        else:
            incomplete.append(label)
    missing = sorted({
        str(path) for item in base_inputs
        for path in (item.injector_path, item.record_path) if not path.is_file()
    })
    return base_inputs, post_inputs, missing, incomplete


def parse_extra_input(spec: str) -> AuditInput:
    """Parse ``LABEL:INJECTOR_PATH:RECORD_PATH`` into one audit input.

    Record sets built outside the batch-6 campaign lineage -- the multi-project
    library replay above all -- have to enter the audit explicitly and under a
    label, never by globbing, so that what the number covers stays legible.
    """
    label, sep, rest = spec.partition(":")
    injector, sep2, record = rest.partition(":")
    if not (sep and sep2 and label and injector and record):
        raise ValueError(
            f"--extra-input expects LABEL:INJECTOR_PATH:RECORD_PATH, got {spec!r}"
        )
    return AuditInput(
        label=label, injector_path=Path(injector), record_path=Path(record),
    )


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-audit", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--out-of-scope", type=Path, default=DEFAULT_OUT_OF_SCOPE)
    parser.add_argument("--audit-out", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument(
        "--extra-input", action="append", default=[],
        metavar="LABEL:INJECTOR:RECORD",
        help=(
            "Fold a record set from outside the batch-6 campaign lineage into "
            "the audit, under an explicit label. Repeatable."
        ),
    )
    args = parser.parse_args()

    base_inputs, post_inputs, missing, incomplete = collect_inputs(args.base_audit)
    extra_inputs = [parse_extra_input(spec) for spec in args.extra_input]
    absent = sorted(
        str(path) for item in extra_inputs
        for path in (item.injector_path, item.record_path) if not path.is_file()
    )
    if absent:
        raise SystemExit(f"--extra-input files are missing: {absent}")
    if missing:
        raise SystemExit(f"audit inputs are missing: {missing}")
    inputs = base_inputs + post_inputs + extra_inputs
    catalog = load_catalog()
    out_of_scope = frozenset(
        line.strip() for line in args.out_of_scope.read_text().splitlines()
        if line.strip()
    )
    paper = paper_scope_names(catalog, out_of_scope)

    # Recompute the batch-6 baseline under each rule so "new versus batch 6" is
    # never a strict numerator compared against an inclusive baseline.
    baselines = {
        rule: build_canonical_audit(
            base_inputs, catalog=catalog, out_of_scope=out_of_scope,
            base_verified_names=frozenset(), base_label="batch0006",
            exclude_opportunistic=(rule == "strict"),
        )["verified_diagnostic_names"]
        for rule in ("strict", "inclusive")
    }
    audits = {
        rule: build_canonical_audit(
            inputs, catalog=catalog, out_of_scope=out_of_scope,
            base_verified_names=baselines[rule], base_label="batch0006",
            exclude_opportunistic=(rule == "strict"),
        )
        for rule in ("strict", "inclusive")
    }
    for rule, audit in audits.items():
        audit["baseline_paper_scope_diagnostic_types"] = len(
            paper & set(baselines[rule])
        )
        audit["declared_campaigns_without_output"] = incomplete
        audit["post_base_campaigns_included"] = [
            item.label for item in post_inputs
        ]
        audit["extra_inputs_included"] = [item.label for item in extra_inputs]

    args.audit_out.parent.mkdir(parents=True, exist_ok=True)
    args.audit_out.write_text(
        json.dumps(audits, indent=2, sort_keys=True) + "\n"
    )

    strict, inclusive = audits["strict"], audits["inclusive"]
    _write_csv(
        args.report_dir / "summary.csv",
        [
            {"metric": key, "strict": strict["counts"][key],
             "inclusive": inclusive["counts"][key]}
            for key in sorted(strict["counts"])
        ] + [
            {"metric": "paper_scope_total_diagnostic_types",
             "strict": strict["paper_scope"]["total_diagnostic_types"],
             "inclusive": inclusive["paper_scope"]["total_diagnostic_types"]},
            {"metric": "paper_scope_verified_diagnostic_types",
             "strict": strict["paper_scope"]["verified_diagnostic_types"],
             "inclusive": inclusive["paper_scope"]["verified_diagnostic_types"]},
            {"metric": "paper_scope_baseline_batch0006_types",
             "strict": strict["baseline_paper_scope_diagnostic_types"],
             "inclusive": inclusive["baseline_paper_scope_diagnostic_types"]},
            {"metric": "paper_scope_new_vs_batch0006_types",
             "strict": len(strict["paper_scope"]["new_vs_base_diagnostic_names"]),
             "inclusive": len(inclusive["paper_scope"]["new_vs_base_diagnostic_names"])},
        ],
        ["metric", "strict", "inclusive"],
    )
    _write_csv(
        args.report_dir / "diagnostic_record_map.csv",
        diagnostic_record_rows(strict),
        [
            "diag_name", "component", "in_paper_scope", "new_vs_base",
            "strict_records", "source_tus", "injector_count", "languages",
            "projects", "strategies", "campaign_count", "injector_ids",
        ],
    )
    _write_csv(
        args.report_dir / "input_manifest.csv",
        strict["input_manifest"],
        ["label", "kind", "path", "sha256", "bytes", "rows"],
    )
    covered = set(strict["diagnostic_index"])
    components = {entry.name: entry.component or "Unknown" for entry in catalog.errors()}
    messages = {entry.name: entry.message for entry in catalog.errors()}
    _write_csv(
        args.report_dir / "uncovered_paper_scope_gaps.csv",
        [
            {
                "diag_name": name,
                "component": components[name],
                "message_template": messages[name],
                "covered_only_by_opportunistic_record": str(
                    name in set(inclusive["diagnostic_index"])
                ).lower(),
            }
            for name in sorted(paper - covered)
        ],
        [
            "diag_name", "component", "message_template",
            "covered_only_by_opportunistic_record",
        ],
    )
    print(json.dumps({
        rule: {
            "paper_scope": audit["paper_scope"]["verified_diagnostic_types"],
            "paper_scope_total": audit["paper_scope"]["total_diagnostic_types"],
            "baseline_batch0006": audit["baseline_paper_scope_diagnostic_types"],
            "new_vs_batch0006": len(
                audit["paper_scope"]["new_vs_base_diagnostic_names"]
            ),
            "strict_verified_records": audit["counts"]["strict_verified_records"],
            "rejections": audit["rejections"],
        }
        for rule, audit in audits.items()
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
