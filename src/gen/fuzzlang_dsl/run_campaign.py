#!/usr/bin/env python3
"""Run a bounded synthesized-Injector campaign on real production TUs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

from foundation.verifier import FuzzlangClangVerifier
from foundation.record import Split
from gen.fuzzlang_dsl.campaign import (
    CampaignBudget,
    load_injectors_jsonl,
    load_records_jsonl,
    run_campaign,
)
from gen.realcorpus.clean_source_pool import load_clean_sources_jsonl


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--injectors", required=True, help="canonical Injector JSONL")
    parser.add_argument(
        "--injector-id",
        dest="injector_ids",
        action="append",
        help=(
            "replay only this Injector ID; repeat to shard a campaign across "
            "workers"
        ),
    )
    parser.add_argument("--sources", help="canonical paired Record JSONL")
    parser.add_argument(
        "--clean-sources",
        help="verified CleanSourceTU JSONL (not a dataset; emitted outputs remain paired)",
    )
    parser.add_argument(
        "--exclude-sources-from-records",
        action="append",
        default=[],
        help=(
            "paired witness Record JSONL whose provenance.source values must be "
            "excluded from replay; repeatable"
        ),
    )
    parser.add_argument(
        "--clean-source-split", choices=("train", "dev", "eval"), default="train",
        help="split assigned to paired records emitted from --clean-sources",
    )
    parser.add_argument("--clang-bin", required=True, help="patched clang++ driver")
    parser.add_argument("--clang-c-bin", required=True, help="patched clang C driver")
    parser.add_argument("--diagtool-bin", required=True)
    parser.add_argument("--records-out", required=True)
    parser.add_argument("--rejections-out", required=True)
    parser.add_argument("--manifest-out", required=True)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--max-verifications", type=_positive_int, default=10_000)
    parser.add_argument(
        "--max-verifications-per-injector", type=_positive_int, default=50,
    )
    parser.add_argument(
        "--max-sources-per-injector", type=_positive_int, default=10_000,
        help="bound real-TU scanning for each Injector before lexical matching",
    )
    parser.add_argument("--max-candidates-per-source", type=_positive_int, default=8)
    parser.add_argument("--max-records", type=_positive_int, default=10_000)
    parser.add_argument("--max-records-per-injector", type=_positive_int, default=50)
    parser.add_argument(
        "--max-records-per-diagnostic",
        type=_positive_int,
        default=10_000,
        help="coverage-first cap across all Injectors with the same target diagnostic",
    )
    parser.add_argument(
        "--checkpoint-every",
        type=_positive_int,
        default=20,
        help=(
            "persist verified replay outputs every N mutant compilations so "
            "long jobs retain completed work before a scheduler timeout"
        ),
    )
    return parser


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _write_jsonl(path: Path, rows) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = "".join(_canonical_json(row) + "\n" for row in rows)
    path.write_text(encoded)
    return encoded.count("\n")


def _file_info(path: Path, *, rows: int | None = None) -> dict[str, Any]:
    payload = path.read_bytes()
    info: dict[str, Any] = {
        "path": str(path),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
    }
    if rows is not None:
        info["records"] = rows
    return info


def _select_injectors(
    injectors, requested_ids: Sequence[str] | None,
):
    """Select requested Injector rows while retaining input-order determinism."""
    if not requested_ids:
        return list(injectors)
    requested = set(requested_ids)
    available = {injector.injector_id for injector in injectors}
    missing = sorted(requested - available)
    if missing:
        raise ValueError(
            "--injector-id not found in --injectors: " + ", ".join(missing)
        )
    return [injector for injector in injectors if injector.injector_id in requested]


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.timeout <= 0:
        _parser().error("--timeout must be positive")
    if not args.sources and not args.clean_sources:
        _parser().error("one of --sources or --clean-sources is required")

    injector_path = Path(args.injectors)
    source_path = Path(args.sources) if args.sources else None
    clean_source_path = Path(args.clean_sources) if args.clean_sources else None
    excluded_record_paths = [
        Path(value) for value in args.exclude_sources_from_records
    ]
    records_path = Path(args.records_out)
    rejections_path = Path(args.rejections_out)
    manifest_path = Path(args.manifest_out)
    output_paths = {records_path.resolve(), rejections_path.resolve(), manifest_path.resolve()}
    if len(output_paths) != 3:
        raise ValueError("records, rejections, and manifest outputs must be distinct")
    input_paths = {injector_path.resolve()}
    if source_path is not None:
        input_paths.add(source_path.resolve())
    if clean_source_path is not None:
        input_paths.add(clean_source_path.resolve())
    input_paths.update(path.resolve() for path in excluded_record_paths)
    if output_paths & input_paths:
        raise ValueError("campaign outputs must not overwrite an input JSONL")

    all_injectors = load_injectors_jsonl(injector_path)
    injectors = _select_injectors(all_injectors, args.injector_ids)
    excluded_source_ids = {
        record.provenance.source
        for path in excluded_record_paths
        for record in load_records_jsonl(path)
    }
    input_source_records = load_records_jsonl(source_path) if source_path else []
    input_clean_sources = (
        load_clean_sources_jsonl(clean_source_path) if clean_source_path else []
    )
    source_records = list(input_source_records)
    clean_sources = list(input_clean_sources)
    excluded_bootstrap_witness_tus = len({
        source.source_id
        for source in [
            *clean_sources,
        ]
        if source.source_id in excluded_source_ids
    })
    source_records = [
        record for record in source_records
        if record.provenance.source not in excluded_source_ids
    ]
    clean_sources = [
        source for source in clean_sources
        if source.source_id not in excluded_source_ids
    ]
    budget = CampaignBudget(
        max_verifications=args.max_verifications,
        max_verifications_per_injector=args.max_verifications_per_injector,
        max_sources_per_injector=args.max_sources_per_injector,
        max_candidates_per_source=args.max_candidates_per_source,
        max_records=args.max_records,
        max_records_per_injector=args.max_records_per_injector,
        max_records_per_diagnostic=args.max_records_per_diagnostic,
    )
    verifier = FuzzlangClangVerifier(
        args.clang_bin,
        args.diagtool_bin,
        args.timeout,
        clang_c_bin=args.clang_c_bin,
    )

    def write_checkpoint(records, rejections) -> None:
        _write_jsonl(records_path, (record.to_dict() for record in records))
        _write_jsonl(rejections_path, (item.to_dict() for item in rejections))

    result = run_campaign(
        injectors,
        source_records,
        verifier,
        clean_sources=clean_sources,
        clean_source_split=Split(args.clean_source_split),
        budget=budget,
        checkpoint_every=args.checkpoint_every,
        checkpoint_callback=write_checkpoint,
    )

    record_count = _write_jsonl(
        records_path, (record.to_dict() for record in result.records),
    )
    rejection_count = _write_jsonl(
        rejections_path, (item.to_dict() for item in result.rejections),
    )
    manifest = {
        "schema": "fuzzlang.synthesized_injector_campaign_manifest",
        "schema_version": 1,
        "llvm_version": "llvmorg-22.1.8",
        "uses_llm_api": False,
        "acceptance_rule": "primary diagnostic name exactly equals Injector target",
        "source_policy": {
            "paired_corrected_src_required": True,
            "clean_source_tu_allowed": True,
            "corrected_clean_gate": True,
            "deduplicate_by": "provenance.source",
            "test_and_test_support_excluded": True,
            "bootstrap_witness_sources_excluded": bool(excluded_record_paths),
        },
        "compiler": {
            "clang_cxx_bin": args.clang_bin,
            "clang_c_bin": args.clang_c_bin,
            "diagtool_bin": args.diagtool_bin,
            "timeout_s": args.timeout,
        },
        "budget": budget.to_dict(),
        "checkpoint_every_mutant_verifications": args.checkpoint_every,
        "budget_usage": dict(result.budget_usage),
        "source_pool": {
            **result.source_pool,
            "excluded_bootstrap_witness_TUs": excluded_bootstrap_witness_tus,
        },
        "scheduling": "deterministic Injector input order, then source input order",
        "metric_definitions": {
            "considered": "language-compatible source TUs reached before a budget cap",
            "matched": "considered clean TUs with at least one lexical application",
            "candidates": "bounded lexical applications returned",
            "compiled": "candidate applications passed to the verifier",
            "exact_target": "compiled candidates whose primary diag_name equals target",
            "near_miss": "failed compiled candidates with a different typed diag_name",
            "clean": "compiled candidates that still compile cleanly",
            "unique_TUs": "distinct provenance.source values among exact outputs",
            "projects": "distinct projects among exact outputs",
            "target_rate": "exact_target / compiled, or 0 when compiled is zero",
        },
        "injectors": [item.to_dict() for item in result.injector_metrics],
        "inputs": {
            "injectors": _file_info(injector_path, rows=len(all_injectors)),
            **(
                {"sources": _file_info(source_path, rows=len(input_source_records))}
                if source_path is not None else {}
            ),
            **(
                {"clean_sources": _file_info(
                    clean_source_path, rows=len(input_clean_sources),
                )}
                if clean_source_path is not None else {}
            ),
            **(
                {"excluded_witness_records": [
                    _file_info(path) for path in excluded_record_paths
                ]}
                if excluded_record_paths else {}
            ),
        },
        "injector_selection": {
            "requested_injector_ids": sorted(set(args.injector_ids or ())),
            "selected_input_rows": len(injectors),
            "selected_injector_ids": sorted({
                injector.injector_id for injector in injectors
            }),
        },
        "outputs": {
            "records": _file_info(records_path, rows=record_count),
            "rejections": _file_info(rejections_path, rows=rejection_count),
        },
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(_canonical_json(manifest) + "\n")
    manifest_sha256 = _file_info(manifest_path)["sha256"]
    print(
        "[campaign] "
        f"records={record_count} rejections={rejection_count} "
        f"manifest_sha256={manifest_sha256} uses_llm_api=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
