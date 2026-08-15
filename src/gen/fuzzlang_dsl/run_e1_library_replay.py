#!/usr/bin/env python3
"""E1: replay the released Injector library on real source. Zero model calls.

Consumes split-labelled source pools (see
`gen/realcorpus/run_freeze_source_splits.py`) and a pinned Injector library,
and reports what the library reaches and what it costs. There is no model
backend here by construction.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from foundation.verifier import FuzzlangClangVerifier
from gen.fuzzlang_dsl.library_replay import (
    DiagnosticBudget, ReplayCaps, ReplayResult, load_injector_library,
    order_library_for_coverage, replay_library,
)
from gen.realcorpus.source_splits import TRAIN


def _load_sources(paths, split: str) -> list[dict]:
    rows: list[dict] = []
    for path in paths:
        for line in Path(path).read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("split") == split:
                rows.append(row)
    return rows


def _merge(shards) -> ReplayResult:
    merged = ReplayResult()
    rejections: dict[str, int] = defaultdict(int)
    reach: dict[str, dict] = {}
    for shard in shards:
        merged.records.extend(shard.records)
        merged.budget.compiler_invocations += shard.budget.compiler_invocations
        for reason, count in shard.rejections.items():
            rejections[reason] += count
        for injector_id, spread in shard.reach.items():
            existing = reach.setdefault(
                injector_id, {"sources": 0, "projects": set()},
            )
            existing["sources"] += spread["sources"]
            existing["projects"].update(spread["projects"])
    merged.rejections = dict(rejections)
    merged.reach = {
        key: {"sources": value["sources"], "projects": sorted(value["projects"])}
        for key, value in sorted(reach.items())
    }
    merged.records.sort(key=lambda record: record.record_id)
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--injectors", type=Path, action="append", required=True)
    parser.add_argument("--sources", type=Path, action="append", required=True)
    parser.add_argument("--split", default=TRAIN)
    parser.add_argument(
        "--operations", choices=("lexical", "append", "all"), default="lexical",
        help="lexical (replace/insert/delete) is the genuine-transfer claim; "
             "an append fragment matches any file, so it is reported separately",
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--clang-bin", required=True)
    parser.add_argument("--clang-c-bin", required=True)
    parser.add_argument("--diagtool-bin", required=True)
    parser.add_argument("--max-records-per-source", type=int, default=3)
    parser.add_argument("--max-records-per-diagnostic", type=int, default=25)
    parser.add_argument("--max-candidates-per-injector", type=int, default=1)
    parser.add_argument("--max-verifications-per-source", type=int, default=24)
    parser.add_argument("--verify-timeout", type=float, default=60.0)
    parser.add_argument("--max-workers", type=int, default=16)
    parser.add_argument(
        "--source-limit", type=int, default=None,
        help="cap sources per project, for a bounded pilot",
    )
    args = parser.parse_args()

    library = load_injector_library(args.injectors)
    if args.operations != "all":
        wanted = (
            {"append"} if args.operations == "append"
            else {"replace", "insert", "delete"}
        )
        library = tuple(i for i in library if i.operation in wanted)
    # Spend each source's scarce verification budget on distinct diagnostics.
    library = order_library_for_coverage(library)
    sources = _load_sources(args.sources, args.split)
    if args.source_limit is not None:
        by_project: dict[str, list[dict]] = defaultdict(list)
        for row in sources:
            by_project[row["project"]].append(row)
        sources = [
            row
            for project in sorted(by_project)
            for row in sorted(
                by_project[project], key=lambda item: item["source_id"],
            )[:args.source_limit]
        ]
    if not library or not sources:
        raise SystemExit(
            f"nothing to replay: {len(library)} Injectors, {len(sources)} sources"
        )

    verifier = FuzzlangClangVerifier(
        args.clang_bin, args.diagtool_bin, timeout_s=args.verify_timeout,
        clang_c_bin=args.clang_c_bin,
    )
    caps = ReplayCaps(
        max_records_per_source=args.max_records_per_source,
        max_records_per_diagnostic=args.max_records_per_diagnostic,
        max_candidates_per_injector=args.max_candidates_per_injector,
        max_verifications_per_source=args.max_verifications_per_source,
    )

    # Shard by source.  The per-diagnostic cap is shared across shards so it is
    # exact, and no verified record is generated only to be discarded later.
    shard_count = max(1, min(args.max_workers, len(sources)))
    shards = [sources[index::shard_count] for index in range(shard_count)]
    diagnostic_budget = DiagnosticBudget(args.max_records_per_diagnostic)
    started = time.time()
    with ThreadPoolExecutor(max_workers=shard_count) as pool:
        results = list(pool.map(
            lambda shard: replay_library(
                library, shard, verifier, caps=caps, split=args.split,
                diagnostic_budget=diagnostic_budget,
            ),
            shards,
        ))
    merged = _merge(results)
    wall = time.time() - started

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "records.jsonl").write_text("".join(
        json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
        for record in merged.records
    ))
    summary = merged.summary()
    summary["wall_seconds"] = round(wall, 3)
    summary["sources_scanned"] = len(sources)
    summary["library_injectors"] = len(library)
    summary["projects_scanned"] = sorted({row["project"] for row in sources})
    summary["split"] = args.split
    summary["per_project_records"] = _per_project(merged)
    manifest = {
        "schema": "fuzzlang.e1_library_replay.v1",
        "uses_llm_api": False,
        "model_calls": 0,
        "llvm_version": "llvmorg-22.1.8",
        "operations": args.operations,
        "caps": {
            "max_verifications_per_source": args.max_verifications_per_source,
            "max_records_per_source": args.max_records_per_source,
            "max_records_per_diagnostic": args.max_records_per_diagnostic,
            "max_candidates_per_injector": args.max_candidates_per_injector,
        },
        "inputs": {
            "injector_files": [
                {"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                for p in args.injectors
            ],
            "source_files": [str(p) for p in args.sources],
        },
        "summary": summary,
    }
    (args.out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    (args.out_dir / "injector_reach.json").write_text(
        json.dumps(merged.reach, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _per_project(result: ReplayResult) -> dict:
    counts: dict[str, dict[str, set]] = defaultdict(
        lambda: {"records": 0, "diagnostics": set(), "sources": set()}
    )
    for record in result.records:
        bucket = counts[record.provenance.detail["project"]]
        bucket["records"] += 1
        bucket["diagnostics"].add(record.provenance.detail["target_diag"])
        bucket["sources"].add(record.provenance.source)
    return {
        project: {
            "records": bucket["records"],
            "diagnostics": len(bucket["diagnostics"]),
            "source_tus": len(bucket["sources"]),
        }
        for project, bucket in sorted(counts.items())
    }


if __name__ == "__main__":
    raise SystemExit(main())
