#!/usr/bin/env python3
"""Release gate for learned-recipe replay records."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from coverage.tracker import INVOCATION_COMPONENTS, build_report
from foundation.diagnostics.catalog import load_catalog
from foundation.record import Record
from foundation.verifier import FuzzlangClangVerifier
from gen.dataset import dedup_records
from gen.realcorpus.corpus import is_test_path
from gen.realcorpus.replay import revalidate_replay_record


def _load(path: Path) -> list[Record]:
    with path.open() as stream:
        return [Record.from_dict(json.loads(line)) for line in stream if line.strip()]


def _load_many(paths: list[Path]) -> list[Record]:
    return [record for path in paths for record in _load(path)]


def _write(path: Path, rows) -> dict:
    sha = hashlib.sha256()
    count = 0
    with path.open("wb") as stream:
        for row in rows:
            line = (json.dumps(row, sort_keys=True) + "\n").encode()
            stream.write(line)
            sha.update(line)
            count += 1
    return {"path": str(path), "records": count, "bytes": path.stat().st_size,
            "sha256": sha.hexdigest()}


def _diag_names(records: list[Record]) -> set[str]:
    return {record.primary_diagnostic.diag_name for record in records
            if record.primary_diagnostic and record.primary_diagnostic.diag_name}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", type=Path, action="append", required=True,
                    help="existing release JSONL; repeat to deduplicate against several")
    ap.add_argument("--input", type=Path, action="append", required=True)
    ap.add_argument("--clang-bin", required=True)
    ap.add_argument("--diagtool-bin", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--manifest-out", type=Path, required=True)
    ap.add_argument("--rejected-out", type=Path, default=None)
    ap.add_argument("--out-of-scope", type=Path, default=None)
    ap.add_argument("--release", default="recipe-replay-v1")
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--timeout", type=float, default=30.0)
    args = ap.parse_args()

    base = _load_many(args.base)
    generated = _load_many(args.input)
    print(f"[revalidate-replay] base={len(base)} generated={len(generated)}", flush=True)
    verifier = FuzzlangClangVerifier(
        args.clang_bin, args.diagtool_bin, timeout_s=args.timeout
    )
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        results = list(executor.map(
            lambda record: revalidate_replay_record(record, verifier), generated
        ))
    statuses = Counter(result.status for result in results)
    validated = [result.record for result in results if result.record is not None]
    print(f"[revalidate-replay] statuses={dict(statuses)}", flush=True)

    combined_deduped = dedup_records([*base, *validated])
    base_ids = {record.record_id for record in base}
    kept_new = [record for record in combined_deduped
                if record.record_id not in base_ids]
    duplicates_removed = len(validated) - len(kept_new)
    combined = [*base, *kept_new]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    output = _write(args.out, (record.to_dict() for record in kept_new))
    rejected_out = args.rejected_out or args.out.with_name("rejected.jsonl")
    rejected = _write(
        rejected_out,
        ({"record_id": record.record_id, "status": result.status}
         for record, result in zip(generated, results) if result.record is None),
    )

    excluded_names = set()
    if args.out_of_scope:
        excluded_names = {line.strip() for line in args.out_of_scope.read_text().splitlines()
                          if line.strip()}
    report = build_report(
        combined, load_catalog(), multiplicity_target=3,
        exclude_components=INVOCATION_COMPONENTS,
        exclude_names=excluded_names,
    )
    base_names = _diag_names(base)
    new_names = _diag_names(kept_new)
    source_overlap = (
        {record.provenance.source for record in base} &
        {record.provenance.source for record in kept_new}
    )
    manifest = {
        "schema_version": 1,
        "release": args.release,
        "uses_llm_api": False,
        "compiler": {
            "required_version": "llvmorg-22.1.8",
            "clang_bin": args.clang_bin,
            "diagtool_bin": args.diagtool_bin,
        },
        "inputs": {
            "base": [str(path) for path in args.base],
            "base_records": len(base),
            "generated": [str(path) for path in args.input],
            "generated_records": len(generated),
        },
        "revalidation": {
            "accepted": len(validated),
            "rejected": len(generated) - len(validated),
            "statuses": dict(sorted(statuses.items())),
            "gate": ["corrected_clean", "buggy_fails", "primary_diag_stable",
                     "source_not_test"],
        },
        "dedup": {
            "validated_new": len(validated),
            "kept_new": len(kept_new),
            "removed_against_base_or_new": duplicates_removed,
        },
        "new_data": {
            "records": len(kept_new),
            "sources": len({record.provenance.source for record in kept_new}),
            "source_overlap_with_base": len(source_overlap),
            "distinct_diagnostics": len(new_names),
            "novel_diagnostics": sorted(new_names - base_names),
            "exact_target": sum(record.provenance.detail["primary_matches_target"]
                                for record in kept_new),
            "near_miss": sum(not record.provenance.detail["primary_matches_target"]
                              for record in kept_new),
            "test_sources": sum(is_test_path(
                record.provenance.detail["source_path"]) for record in kept_new),
            "corrected_src_missing": sum(
                not record.corrected_src for record in kept_new),
        },
        "combined": {
            "records": len(combined),
            "distinct_observed_diagnostics": len(_diag_names(combined)),
            "strict_code_coverage": {
                "covered": report.covered,
                "total": report.total,
                "rate": report.coverage_fraction,
                "covered_at_multiplicity_3": report.covered_at_target,
            },
        },
        "files": {"records": output, "rejected": rejected},
    }
    args.manifest_out.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    print(f"[revalidate-replay] kept={len(kept_new)} duplicates={duplicates_removed}",
          flush=True)
    print(f"[revalidate-replay] coverage={report.covered}/{report.total} "
          f"@3={report.covered_at_target}", flush=True)
    print(f"[revalidate-replay] manifest -> {args.manifest_out}", flush=True)


if __name__ == "__main__":
    main()
