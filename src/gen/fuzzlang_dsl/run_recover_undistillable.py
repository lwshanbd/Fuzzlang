#!/usr/bin/env python3
"""Recover portable Injectors from archived exact undistillable pairs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from foundation.record import Record
from foundation.verifier import FuzzlangClangVerifier
from gen.fuzzlang_dsl.context_variants import load_excluded_injector_ids
from gen.fuzzlang_dsl.undistillable_recovery import (
    recover_comment_replacement,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        for row in rows
    ))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--clang-bin", required=True)
    parser.add_argument("--clang-c-bin", required=True)
    parser.add_argument("--diagtool-bin", required=True)
    parser.add_argument("--records-out", type=Path, required=True)
    parser.add_argument("--injectors-out", type=Path, required=True)
    parser.add_argument("--manifest-out", type=Path, required=True)
    parser.add_argument(
        "--exclude-injectors",
        type=Path,
        action="append",
        default=[],
    )
    parser.add_argument("--timeout", type=float, default=15)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    records = [
        Record.from_dict(json.loads(line))
        for line in args.records.read_text().splitlines()
        if line.strip()
    ]
    excluded = frozenset(
        load_excluded_injector_ids(args.exclude_injectors)
    )
    verifier = FuzzlangClangVerifier(
        args.clang_bin,
        args.diagtool_bin,
        args.timeout,
        clang_c_bin=args.clang_c_bin,
    )
    recovered_records: dict[str, dict] = {}
    injectors: dict[str, dict] = {}
    recovered_diagnostics: set[str] = set()
    for record in records:
        target = record.primary_diagnostic
        if target is None or target.diag_name in recovered_diagnostics:
            continue
        recovery = recover_comment_replacement(record, verifier)
        if recovery is None:
            continue
        new_injectors = {
            injector.injector_id: injector.to_dict()
            for injector in recovery.injectors
            if injector.injector_id not in excluded
        }
        if not new_injectors:
            continue
        recovered_records[recovery.record.record_id] = (
            recovery.record.to_dict()
        )
        injectors.update(new_injectors)
        recovered_diagnostics.add(target.diag_name)

    _write_jsonl(args.records_out, list(recovered_records.values()))
    _write_jsonl(args.injectors_out, list(injectors.values()))
    manifest = {
        "schema": "fuzzlang.undistillable_recovery.v1",
        "counts": {
            "input_records": len(records),
            "recovered_records": len(recovered_records),
            "recovered_diagnostic_types": len(recovered_diagnostics),
            "portable_injectors": len(injectors),
            "excluded_injectors": len(excluded),
        },
    }
    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_out.write_text(
        json.dumps(manifest, sort_keys=True) + "\n"
    )
    print(json.dumps(manifest["counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

