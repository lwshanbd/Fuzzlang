#!/usr/bin/env python3
"""Re-clean-gate real C++ source under a designated standard mode."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from foundation.verifier import FuzzlangClangVerifier
from gen.realcorpus.clean_source_pool import (
    load_clean_sources_jsonl,
    revalidate_cpp_standard_pool,
)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _write_jsonl(path: Path, values: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
        for value in values
    )
    path.write_text(payload)
    return payload.count("\n")


def _file_info(path: Path, *, rows: int) -> dict[str, Any]:
    payload = path.read_bytes()
    return {
        "path": str(path),
        "bytes": len(payload),
        "records": rows,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean-sources", type=Path, required=True)
    parser.add_argument("--standard", required=True, help="e.g. c++20")
    parser.add_argument("--clang-bin", required=True)
    parser.add_argument("--clang-c-bin", required=True)
    parser.add_argument("--diagtool-bin", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--rejections-out", type=Path, required=True)
    parser.add_argument("--manifest-out", type=Path, required=True)
    parser.add_argument("--workers", type=_positive_int, default=16)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--llvm-version", default="llvmorg-22.1.8")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.timeout <= 0:
        _parser().error("--timeout must be positive")
    output_paths = {args.out.resolve(), args.rejections_out.resolve(), args.manifest_out.resolve()}
    if len(output_paths) != 3:
        raise ValueError("out, rejections-out, and manifest-out must be distinct")
    sources = load_clean_sources_jsonl(args.clean_sources)
    verifier = FuzzlangClangVerifier(
        args.clang_bin, args.diagtool_bin, timeout_s=args.timeout,
        clang_c_bin=args.clang_c_bin,
    )
    result = revalidate_cpp_standard_pool(
        sources, verifier, standard=args.standard, workers=args.workers,
    )
    accepted = _write_jsonl(args.out, (item.to_dict() for item in result.sources))
    rejected = _write_jsonl(
        args.rejections_out, (item.to_dict() for item in result.rejections),
    )
    manifest = {
        "schema": "fuzzlang.restandardized_clean_source_pool_manifest",
        "schema_version": 1,
        "llvm_version": args.llvm_version,
        "uses_llm_api": False,
        "source_policy": {
            "production_source_only": True,
            "test_and_test_support_excluded": True,
            "original_source_text_preserved": True,
            "clean_compiler_gate": True,
        },
        "compile_mode": {"language": "c++", "standard": args.standard},
        "compiler": {
            "clang_cxx_bin": args.clang_bin,
            "clang_c_bin": args.clang_c_bin,
            "diagtool_bin": args.diagtool_bin,
            "timeout_s": args.timeout,
        },
        "counts": dict(result.counts),
        "inputs": {"clean_sources": str(args.clean_sources)},
        "outputs": {
            "sources": _file_info(args.out, rows=accepted),
            "rejections": _file_info(args.rejections_out, rows=rejected),
        },
    }
    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_out.write_text(json.dumps(manifest, separators=(",", ":"), sort_keys=True) + "\n")
    print(f"[restandardized-clean-source-pool] sources={accepted} rejections={rejected} uses_llm_api=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
