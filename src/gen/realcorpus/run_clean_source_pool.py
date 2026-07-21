#!/usr/bin/env python3
"""Export a compiler-verified pool of unseen real production source files."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from foundation.compile_db import load_compile_db
from foundation.record import Record
from foundation.verifier import FuzzlangClangVerifier
from gen.realcorpus.clean_source_pool import (
    build_clean_source_pool,
    load_clean_sources_jsonl,
)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compile-db", type=Path, required=True)
    parser.add_argument("--clang-bin", required=True, help="patched clang++")
    parser.add_argument("--clang-c-bin", required=True, help="patched clang")
    parser.add_argument("--diagtool-bin", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument(
        "--source-root", required=True,
        help="checkout root; output paths are stored relative to it",
    )
    parser.add_argument("--source-substr", default=None)
    parser.add_argument(
        "--exclude-records", type=Path, action="append", default=[],
        help="paired Record JSONL whose provenance.source values are excluded",
    )
    parser.add_argument(
        "--exclude-clean-sources", type=Path, action="append", default=[],
        help="CleanSourceTU JSONL whose source_id values are excluded",
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--rejections-out", type=Path, required=True)
    parser.add_argument("--manifest-out", type=Path, required=True)
    parser.add_argument(
        "--max-files", type=int, default=0,
        help="0 processes all deterministic candidates",
    )
    parser.add_argument("--workers", type=_positive_int, default=16)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--llvm-version", default="llvmorg-22.1.8")
    return parser


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _write_jsonl(path: Path, values: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(_canonical_json(value) + "\n" for value in values)
    path.write_text(payload)
    return payload.count("\n")


def _file_info(path: Path, *, rows: int | None = None) -> dict[str, Any]:
    payload = path.read_bytes()
    result: dict[str, Any] = {
        "path": str(path),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    if rows is not None:
        result["records"] = rows
    return result


def _record_source_ids(paths: Sequence[Path]) -> tuple[set[str], int]:
    source_ids: set[str] = set()
    rows = 0
    for path in paths:
        for line_number, line in enumerate(path.read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                source_ids.add(Record.from_dict(value).provenance.source)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise ValueError(f"{path}:{line_number}: invalid Record exclusion: {error}") from error
            rows += 1
    return source_ids, rows


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
    if args.out.resolve() in {args.compile_db.resolve(), *(path.resolve() for path in args.exclude_records), *(path.resolve() for path in args.exclude_clean_sources)}:
        raise ValueError("--out must not overwrite an input")

    excluded, excluded_record_rows = _record_source_ids(args.exclude_records)
    excluded_clean_rows = 0
    for path in args.exclude_clean_sources:
        sources = load_clean_sources_jsonl(path)
        excluded.update(source.source_id for source in sources)
        excluded_clean_rows += len(sources)

    compile_db = load_compile_db(args.compile_db)
    verifier = FuzzlangClangVerifier(
        args.clang_bin,
        args.diagtool_bin,
        timeout_s=args.timeout,
        clang_c_bin=args.clang_c_bin,
    )
    result = build_clean_source_pool(
        compile_db,
        verifier,
        project=args.project,
        source_root=args.source_root,
        source_substr=args.source_substr,
        excluded_source_ids=excluded,
        max_files=(None if args.max_files == 0 else args.max_files),
        workers=args.workers,
        baseline_compiler=args.llvm_version,
    )
    source_rows = _write_jsonl(args.out, (source.to_dict() for source in result.sources))
    rejection_rows = _write_jsonl(
        args.rejections_out, (rejection.to_dict() for rejection in result.rejections),
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
            "stored_paths_are_project_relative": True,
        },
        "compiler": {
            "clang_cxx_bin": args.clang_bin,
            "clang_c_bin": args.clang_c_bin,
            "diagtool_bin": args.diagtool_bin,
            "timeout_s": args.timeout,
        },
        "selection": {
            "project": args.project,
            "source_root": args.source_root,
            "source_substr": args.source_substr,
            "max_files": args.max_files,
            "scheduling": "lexicographic compile-database path order",
            "excluded_record_rows": excluded_record_rows,
            "excluded_clean_source_rows": excluded_clean_rows,
            "excluded_unique_source_ids": len(excluded),
        },
        "counts": dict(result.counts),
        "inputs": {
            "compile_db": _file_info(args.compile_db),
            "exclude_records": [str(path) for path in args.exclude_records],
            "exclude_clean_sources": [str(path) for path in args.exclude_clean_sources],
        },
        "outputs": {
            "sources": _file_info(args.out, rows=source_rows),
            "rejections": _file_info(args.rejections_out, rows=rejection_rows),
        },
    }
    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_out.write_text(_canonical_json(manifest) + "\n")
    print(
        "[clean-source-pool] "
        f"sources={source_rows} rejections={rejection_rows} "
        f"uses_llm_api=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
