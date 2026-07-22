#!/usr/bin/env python3
"""Revalidate paired real-source parents into a clean-source replay pool.

Unlike :mod:`run_clean_source_pool`, this entry point consumes existing paired
records whose provenance already carries the source-relative path and original
compile command.  It still compiles every deduplicated correct parent with the
currently pinned FuzzLang Clang before exporting it as a clean source.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, Sequence

from foundation.record import Record
from foundation.verifier import FuzzlangClangVerifier
from gen.realcorpus.clean_source_pool import build_clean_source_pool_from_records
from gen.realcorpus.run_clean_source_pool import (
    _canonical_json,
    _file_info,
    _write_jsonl,
)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--records", type=Path, action="append", required=True,
        help="paired Record JSONL; may be supplied more than once",
    )
    parser.add_argument("--clang-bin", required=True, help="patched clang++")
    parser.add_argument("--clang-c-bin", required=True, help="patched clang")
    parser.add_argument("--diagtool-bin", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--rejections-out", type=Path, required=True)
    parser.add_argument("--manifest-out", type=Path, required=True)
    parser.add_argument(
        "--exclude-clean-sources", type=Path, action="append", default=[],
        help="CleanSourceTU JSONL whose source_id values are excluded",
    )
    parser.add_argument("--max-files", type=int, default=0)
    parser.add_argument("--workers", type=_positive_int, default=16)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--llvm-version", default="llvmorg-22.1.8")
    return parser


def _load_records(paths: Iterable[Path]) -> list[Record]:
    records: list[Record] = []
    for path in paths:
        for line_number, line in enumerate(path.read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("row must be a JSON object")
                records.append(Record.from_dict(value))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise ValueError(f"{path}:{line_number}: invalid Record: {error}") from error
    return records


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.timeout <= 0:
        _parser().error("--timeout must be positive")
    if args.max_files < 0:
        _parser().error("--max-files must be non-negative")
    output_paths = {
        args.out.resolve(), args.rejections_out.resolve(), args.manifest_out.resolve(),
    }
    if len(output_paths) != 3:
        raise ValueError("out, rejections-out, and manifest-out must be distinct")
    if args.out.resolve() in {path.resolve() for path in args.records}:
        raise ValueError("--out must not overwrite a paired-record input")

    from gen.realcorpus.clean_source_pool import load_clean_sources_jsonl

    excluded: set[str] = set()
    for path in args.exclude_clean_sources:
        excluded.update(source.source_id for source in load_clean_sources_jsonl(path))
    records = _load_records(args.records)
    verifier = FuzzlangClangVerifier(
        args.clang_bin,
        args.diagtool_bin,
        timeout_s=args.timeout,
        clang_c_bin=args.clang_c_bin,
    )
    result = build_clean_source_pool_from_records(
        records,
        verifier,
        project=args.project,
        excluded_source_ids=excluded,
        max_files=(None if args.max_files == 0 else args.max_files),
        workers=args.workers,
        baseline_compiler=args.llvm_version,
    )
    source_rows = _write_jsonl(args.out, (item.to_dict() for item in result.sources))
    rejection_rows = _write_jsonl(
        args.rejections_out, (item.to_dict() for item in result.rejections),
    )
    manifest = {
        "schema": "fuzzlang.clean_source_pool_manifest",
        "schema_version": 1,
        "llvm_version": args.llvm_version,
        "uses_llm_api": False,
        "source_policy": {
            "production_source_only": True,
            "test_and_test_support_excluded": True,
            "clean_compiler_gate": True,
            "paired_dataset_records_emitted": False,
            "record_derived_parents_revalidated": True,
        },
        "compiler": {
            "clang_cxx_bin": args.clang_bin,
            "clang_c_bin": args.clang_c_bin,
            "diagtool_bin": args.diagtool_bin,
            "timeout_s": args.timeout,
        },
        "selection": {
            "project": args.project,
            "max_files": args.max_files,
            "scheduling": "lexicographic project-relative path order",
            "excluded_clean_source_rows": len(excluded),
        },
        "counts": dict(result.counts),
        "inputs": {"paired_records": [_file_info(path) for path in args.records]},
        "outputs": {
            "sources": _file_info(args.out, rows=source_rows),
            "rejections": _file_info(args.rejections_out, rows=rejection_rows),
        },
    }
    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_out.write_text(_canonical_json(manifest) + "\n")
    print(f"[clean-source-pool-from-records] sources={source_rows} rejections={rejection_rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
