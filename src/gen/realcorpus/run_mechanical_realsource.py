#!/usr/bin/env python3
"""Generate bounded mechanical errors from clean real-project source Records."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from foundation.record import Record
from foundation.verifier import FuzzlangClangVerifier
from gen.mutate import get, text_mutations
from gen.realcorpus.corpus import is_test_path
from gen.realcorpus.mechanical import (
    MechanicalOutcome,
    mutate_real_source,
    select_real_source_records,
)


def _load(path: Path) -> list[Record]:
    with path.open() as stream:
        return [
            Record.from_dict(json.loads(line))
            for line in stream if line.strip()
        ]


def _write_jsonl(path: Path, rows) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256()
    count = 0
    with path.open("wb") as stream:
        for row in rows:
            line = (json.dumps(row, sort_keys=True) + "\n").encode("utf-8")
            stream.write(line)
            sha.update(line)
            count += 1
    return {
        "path": str(path),
        "records": count,
        "bytes": path.stat().st_size,
        "sha256": sha.hexdigest(),
    }


def _input_metadata(path: Path, records: int) -> dict:
    sha = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            sha.update(chunk)
            size += len(chunk)
    return {
        "path": str(path),
        "records": records,
        "bytes": size,
        "sha256": sha.hexdigest(),
    }


def _global_rejection(status: str, record: Record) -> dict:
    detail = record.provenance.detail
    return {
        "status": status,
        "parent_record_id": detail.get("parent_record_id"),
        "source": record.provenance.source,
        "source_path": detail.get("source_path"),
        "mutation": detail.get("mutation"),
        "description": detail.get("description"),
        "mutant_hash": hashlib.sha256(
            record.erroneous_src.encode("utf-8")
        ).hexdigest(),
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Apply bounded deterministic text mutations to corrected source from "
            "canonical RealSource Records."
        )
    )
    ap.add_argument("--input", type=Path, action="append", required=True,
                    help="canonical paired Record JSONL; repeat to combine releases")
    ap.add_argument("--clang-bin", required=True)
    ap.add_argument(
        "--clang-c-bin", default=None,
        help="C driver; defaults to --clang-bin when both languages use one driver",
    )
    ap.add_argument("--diagtool-bin", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--manifest-out", type=Path, required=True)
    ap.add_argument("--rejected-out", type=Path, default=None)
    ap.add_argument("--mutation", action="append", default=[],
                    help="registered text mutation name; repeat; default is all text")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-sources", type=int, default=100,
                    help="0 keeps every eligible unique source")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--max-candidates-per-mutation", type=int, default=2)
    ap.add_argument("--max-verifications-per-source", type=int, default=8)
    ap.add_argument("--max-records-per-source", type=int, default=3)
    ap.add_argument("--max-instances-per-diagnostic", type=int, default=5,
                    help="0 disables the global diagnostic cap")
    ap.add_argument("--max-instances", type=int, default=300)
    args = ap.parse_args()

    if args.max_sources < 0:
        ap.error("--max-sources must be non-negative")
    for name in (
        "max_candidates_per_mutation",
        "max_verifications_per_source",
        "max_records_per_source",
    ):
        if getattr(args, name) < 0:
            ap.error(f"--{name.replace('_', '-')} must be non-negative")
    if args.max_instances <= 0:
        ap.error("--max-instances must be positive")
    if args.max_instances_per_diagnostic < 0:
        ap.error("--max-instances-per-diagnostic must be non-negative")

    if args.mutation:
        try:
            mutations = [get(name) for name in args.mutation]
        except KeyError as error:
            ap.error(str(error))
    else:
        mutations = text_mutations()

    input_records: list[Record] = []
    input_files = []
    for path in args.input:
        loaded = _load(path)
        input_records.extend(loaded)
        input_files.append(_input_metadata(path, len(loaded)))
    selection = select_real_source_records(input_records)
    candidates = list(selection.records)
    random.Random(args.seed).shuffle(candidates)
    if args.max_sources > 0:
        candidates = candidates[:args.max_sources]

    verifier = FuzzlangClangVerifier(
        args.clang_bin,
        args.diagtool_bin,
        timeout_s=args.timeout,
        clang_c_bin=args.clang_c_bin,
    )

    def work(record: Record) -> MechanicalOutcome:
        return mutate_real_source(
            record,
            verifier,
            mutations=mutations,
            seed=args.seed,
            max_candidates_per_mutation=args.max_candidates_per_mutation,
            max_verifications=args.max_verifications_per_source,
            max_records=args.max_records_per_source,
        )

    records: list[Record] = []
    rejected_rows = [
        rejection.to_dict() for rejection in selection.rejections
    ]
    source_statuses: Counter[str] = Counter()
    diagnostic_counts: Counter[str] = Counter()
    baseline_compiles = 0
    mutant_compiles = 0
    candidates_selected = 0
    sources_scanned = 0
    accepted_before_global_caps = 0
    chunk_size = max(1, args.workers * 2)
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        for base in range(0, len(candidates), chunk_size):
            chunk = candidates[base:base + chunk_size]
            for outcome in executor.map(work, chunk):
                sources_scanned += 1
                source_statuses[outcome.status] += 1
                baseline_compiles += outcome.baseline_compiles
                mutant_compiles += outcome.mutant_compiles
                candidates_selected += outcome.candidates_selected
                rejected_rows.extend(
                    rejection.to_dict() for rejection in outcome.rejections
                )
                accepted_before_global_caps += len(outcome.records)
                for record in outcome.records:
                    if len(records) >= args.max_instances:
                        rejected_rows.append(_global_rejection(
                            "global_record_cap", record
                        ))
                        continue
                    diag_name = record.primary_diagnostic.diag_name
                    if (
                        args.max_instances_per_diagnostic > 0
                        and diagnostic_counts[diag_name]
                        >= args.max_instances_per_diagnostic
                    ):
                        rejected_rows.append(_global_rejection(
                            "global_diagnostic_cap", record
                        ))
                        continue
                    diagnostic_counts[diag_name] += 1
                    records.append(record)
            print(
                f"[mechanical-realsource] scanned={sources_scanned} "
                f"records={len(records)} mutant_compiles={mutant_compiles}",
                flush=True,
            )
            if len(records) >= args.max_instances:
                break

    records = records[:args.max_instances]
    rejected_out = args.rejected_out or args.out.with_name("rejected.jsonl")
    output_file = _write_jsonl(
        args.out, (record.to_dict() for record in records)
    )
    rejected_file = _write_jsonl(rejected_out, rejected_rows)
    rejection_statuses = Counter(
        row["status"] for row in rejected_rows
    )
    manifest = {
        "schema_version": 1,
        "generator": "mechanical_real_source",
        "uses_llm_api": False,
        "inputs": {
            "paths": [str(path) for path in args.input],
            "records": len(input_records),
            "files": input_files,
        },
        "selection": {
            "eligible_unique_sources": len(selection.records),
            "scheduled_sources": len(candidates),
            "statuses": dict(sorted(selection.statuses.items())),
        },
        "mutations": [mutation.name for mutation in mutations],
        "compilation": {
            "baseline_compiles": baseline_compiles,
            "mutant_compiles": mutant_compiles,
            "total_compiles": baseline_compiles + mutant_compiles,
        },
        "run": {
            "sources_scanned": sources_scanned,
            "source_statuses": dict(sorted(source_statuses.items())),
            "candidates_selected": candidates_selected,
            "accepted_before_global_caps": accepted_before_global_caps,
            "accepted": len(records),
            "rejection_statuses": dict(sorted(rejection_statuses.items())),
            "distinct_diagnostics": len(diagnostic_counts),
            "test_sources": sum(
                is_test_path(record.provenance.detail["source_path"])
                for record in records
            ),
            "corrected_src_missing": sum(
                not record.corrected_src for record in records
            ),
        },
        "limits": {
            "seed": args.seed,
            "max_sources": args.max_sources,
            "workers": args.workers,
            "timeout": args.timeout,
            "max_candidates_per_mutation": args.max_candidates_per_mutation,
            "max_verifications_per_source": args.max_verifications_per_source,
            "max_records_per_source": args.max_records_per_source,
            "max_instances_per_diagnostic": args.max_instances_per_diagnostic,
            "max_instances": args.max_instances,
        },
        "compiler": {
            "clang_bin": args.clang_bin,
            "clang_c_bin": args.clang_c_bin or args.clang_bin,
            "diagtool_bin": args.diagtool_bin,
            "required_version": "llvmorg-22.1.8",
        },
        "files": {
            "records": output_file,
            "rejected": rejected_file,
        },
    }
    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_out.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    print(
        f"[mechanical-realsource] DONE records={len(records)} "
        f"diagnostics={len(diagnostic_counts)}",
        flush=True,
    )
    print(f"[mechanical-realsource] manifest -> {args.manifest_out}", flush=True)


if __name__ == "__main__":
    main()
