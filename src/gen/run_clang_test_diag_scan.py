#!/usr/bin/env python3
"""Scan one batch of Clang regression tests for emitted diagnostic IDs.

This is coverage evidence only.  It never creates FuzzLang Records and never
exports test sources as dataset material.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from foundation.verifier import FuzzlangClangVerifier
from gen.guided.examples import mine, sweep_configs
from gen.guided.runline import (
    parse_analyzer_configs,
    parse_cc1_configs,
    parse_cl_configs,
    parse_driver_configs,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=Path, required=True,
                        help="newline-delimited clang/test source paths")
    parser.add_argument("--clang", required=True)
    parser.add_argument("--clang-c", required=True)
    parser.add_argument("--diagtool", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=32)
    parser.add_argument("--max-cc1-per-file", type=int, default=4)
    args = parser.parse_args()
    if args.workers <= 0 or args.max_cc1_per_file < 0:
        parser.error("workers must be positive and max-cc1-per-file non-negative")
    paths = [Path(line) for line in args.files.read_text().splitlines() if line.strip()]
    sources = [(path.read_text(encoding="utf-8", errors="replace"), str(path))
               for path in paths]
    resource_dir = subprocess.run(
        [args.clang, "-print-resource-dir"], capture_output=True, text=True,
        check=True,
    ).stdout.strip()
    verifier = FuzzlangClangVerifier(
        args.clang, args.diagtool, timeout_s=15.0, clang_c_bin=args.clang_c,
    )

    def runline_configs(source: str, _path: str) -> list[list[str]]:
        return (parse_cc1_configs(source, resource_dir=resource_dir)[:args.max_cc1_per_file]
                + parse_driver_configs(source)
                + parse_analyzer_configs(source, resource_dir=resource_dir)[:args.max_cc1_per_file]
                + parse_cl_configs(source))

    examples, configs = mine(
        sources, verifier, compile_cmds=sweep_configs(),
        per_source_cmds=runline_configs, max_per_diag=1,
        max_configs_per_diag=3, workers=args.workers,
    )
    payload = {
        "schema": "fuzzlang.clang_test_diagnostic_scan.v1",
        "dataset_policy": "coverage_evidence_only_no_test_source_records",
        "inputs": {"files_list": str(args.files), "test_files": len(paths)},
        "compiler": {"clang": args.clang, "clang_c": args.clang_c,
                     "diagtool": args.diagtool, "resource_dir": resource_dir},
        "scan": {"sweep_configs": len(sweep_configs()),
                 "max_cc1_per_file": args.max_cc1_per_file,
                 "workers": args.workers},
        "diagnostic_names": sorted(examples),
        "diagnostic_count": len(examples),
        "trigger_configs": {name: configs[name] for name in sorted(configs)},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"[clang-test-scan] files={len(paths)} diagnostics={len(examples)} out={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
