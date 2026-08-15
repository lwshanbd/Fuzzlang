#!/usr/bin/env python3
"""Freeze verified records into a citable dataset release.

Reads the generated record files, drops fetched-dependency source, regroups on
the split frozen before generation, checks every release gate, and writes the
split files plus a manifest with checksums. **A violation aborts the freeze** --
a release with a known-broken record is worse than no release, because the
manifest is what other people will trust instead of re-checking.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Sequence

from gen.fuzzlang_dsl.dataset_release import (
    RELEASE_INVARIANTS,
    split_records,
    split_summary,
    verify_invariants,
)
from gen.realcorpus.corpus import is_vendored_path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(paths: Sequence[str]) -> list[dict]:
    records: list[dict] = []
    for path in paths:
        for line in Path(path).read_text().splitlines():
            if line.strip():
                records.append(json.loads(line))
    return records


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", action="append", required=True)
    parser.add_argument("--release", required=True, help="Release name, e.g. fuzzlang-realsource-v1")
    parser.add_argument("--created", required=True, help="ISO date; passed in so the manifest is reproducible")
    parser.add_argument("--injector-library")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument(
        "--keep-vendored", action="store_true",
        help="Do not drop fetched-dependency source. Off by design.",
    )
    args = parser.parse_args(argv)

    raw = _load(args.records)
    kept = [
        record for record in raw
        if args.keep_vendored or not is_vendored_path(
            str(((record.get("provenance") or {}).get("detail") or {}).get("source_path") or "")
        )
    ]
    dropped_vendored = len(raw) - len(kept)

    violations = verify_invariants(kept)
    if violations:
        print(json.dumps({"refused": True, "violations": {
            gate: {"count": len(ids), "examples": ids[:5]}
            for gate, ids in violations.items()
        }}, indent=2))
        print("\nRelease refused: fix the records or the gate, not the manifest.",
              file=sys.stderr)
        return 1

    splits = split_records(kept)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    files = {}
    for split, records in splits.items():
        path = out / f"{split}.jsonl"
        path.write_text(
            "".join(json.dumps(record, sort_keys=True) + "\n" for record in records)
        )
        files[split] = {
            "path": path.name,
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
            **split_summary(records),
        }

    all_diags = {
        str(((r.get("provenance") or {}).get("detail") or {}).get("target_diag"))
        for r in kept
    }
    manifest = {
        "schema_version": 1,
        "release": args.release,
        "created": args.created,
        "compiler": {
            "llvm_tag": "llvmorg-22.1.8",
            "verifier": "Fuzzlang-patched clang with DiagID emission",
        },
        "method": {
            "name": "FuzzLang Injector library replay over clean real-project source",
            "uses_llm_api": False,
            "gpu_hours": 0.0,
            "model_calls": 0,
            "injector_library": args.injector_library,
            "injector_library_sha256": (
                _sha256(Path(args.injector_library)) if args.injector_library else None
            ),
        },
        "totals": {
            "records": len(kept),
            "diagnostics": len(all_diags),
            "source_files": len({
                str(((r.get("provenance") or {}).get("detail") or {}).get("source_path"))
                for r in kept
            }),
            "vendored_records_dropped": dropped_vendored,
        },
        "splits": files,
        # Splits come from a fixed hash of the source, so pool growth never
        # reassigns a source that has already been used.
        "split_policy": "frozen before generation; carried per record in provenance.detail.source_split",
        "release_gates": {gate: "pass" for gate in RELEASE_INVARIANTS},
        "inputs": {
            "records": list(args.records),
            "records_sha256": {p: _sha256(Path(p)) for p in args.records},
        },
    }
    (out / "release-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({"release": args.release, "totals": manifest["totals"],
                      "splits": {k: v["records"] for k, v in files.items()}},
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
