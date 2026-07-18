#!/usr/bin/env python3
"""Revalidate and formalize flat real-corpus rows as canonical Records.

The generation driver streams a compact, repair-ready row.  A release needs a
stronger gate: recover provenance for legacy rows, reject test sources, compile
both sides again under the recorded command, require the recorded primary
diagnostic to remain stable, then deduplicate and carve source-isolated splits.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Optional

from foundation.compile_db import load_compile_db
from foundation.record import Origin, Provenance, Record, Split
from foundation.verifier import FuzzlangClangVerifier
from foundation.verifier.base import BaseVerifier
from gen.dataset import dedup_records, split_records
from gen.realcorpus.collect import count_errors
from gen.realcorpus.corpus import is_test_path


@dataclass(frozen=True)
class CanonicalizeResult:
    status: str
    record: Optional[Record] = None
    detail: str = ""


def portable_source_path(path: str) -> str:
    """Remove machine-specific checkout prefixes from an LLVM source path."""
    normalized = path.replace("\\", "/")
    marker = "/external/llvm-project/"
    if marker in normalized:
        return normalized.split(marker, 1)[1]
    return normalized.removeprefix("external/llvm-project/")


def _source_hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def build_corrected_source_index(paths: Iterable[str]) -> dict[str, tuple[str, ...]]:
    """Map exact source contents to all non-test compile-DB paths containing it."""
    by_hash: dict[str, list[str]] = defaultdict(list)
    for raw_path in paths:
        if is_test_path(raw_path):
            continue
        try:
            source = Path(raw_path).read_text(errors="replace")
        except OSError:
            continue
        by_hash[_source_hash(source)].append(raw_path)
    return {key: tuple(sorted(set(values))) for key, values in by_hash.items()}


def _resolve_source_path(
    row: dict, source_index: dict[str, tuple[str, ...]]
) -> tuple[Optional[str], str]:
    explicit = row.get("source_path")
    if explicit:
        return str(explicit), "explicit"
    matches = source_index.get(_source_hash(row["corrected_src"]), ())
    if len(matches) == 1:
        return matches[0], "corrected_source_hash"
    if not matches:
        return None, "source_unresolved"
    return None, "source_ambiguous"


def canonicalize_row(
    row: dict,
    verifier: BaseVerifier,
    *,
    source_index: dict[str, tuple[str, ...]],
) -> CanonicalizeResult:
    """Apply the release gate to one flat row and return a canonical Record."""
    source_path, resolution = _resolve_source_path(row, source_index)
    if source_path is None:
        return CanonicalizeResult(resolution)
    if is_test_path(source_path):
        return CanonicalizeResult("test_source", detail=source_path)

    logical_path = portable_source_path(source_path)
    compile_cmd = row.get("compile_cmd")
    if not isinstance(compile_cmd, list) or "__SRC__" not in compile_cmd:
        return CanonicalizeResult("invalid_compile_cmd")

    corrected = verifier.verify(
        row["corrected_src"], compile_cmd, logical_path=logical_path
    )
    if not corrected.ok:
        return CanonicalizeResult("corrected_not_clean")

    buggy = verifier.verify(row["buggy_src"], compile_cmd, logical_path=logical_path)
    if buggy.ok:
        return CanonicalizeResult("buggy_became_clean")
    if buggy.diag is None:
        return CanonicalizeResult("missing_primary_diagnostic")
    expected_name = row.get("diag_name")
    if expected_name and buggy.diag.diag_name != expected_name:
        return CanonicalizeResult(
            "diagnostic_drift",
            detail=f"{expected_name}->{buggy.diag.diag_name}",
        )

    diag = replace(buggy.diag, file=logical_path)
    target = row.get("target_diag")
    target_match = bool(target and diag.diag_name == target)
    generation_label = "exact_target" if target_match else "near_miss"
    project = row.get("project") or "llvm"
    cascade_size = max(1, count_errors(buggy.raw_stderr))
    detail = {
        "strategy": "realcorpus_inject",
        "generator": "llm_localized_edit",
        "target_diag": target,
        "primary_matches_target": target_match,
        "generation_label": generation_label,
        "cascade_size": cascade_size,
        "region": row.get("region"),
        "region_type": row.get("region_type"),
        "compile_cmd": compile_cmd,
        "source_path": logical_path,
        "source_resolution": resolution,
        "revalidated": True,
        "recorded_diag_id": row.get("diag_id"),
        "recorded_diag_name": expected_name,
    }
    record = Record(
        record_id=row["instance_id"],
        erroneous_src=row["buggy_src"],
        corrected_src=row["corrected_src"],
        diagnostics=(diag,),
        provenance=Provenance(
            origin=Origin.LLM,
            source=f"{project}:{logical_path}",
            detail=detail,
        ),
        split=Split.EVAL,
        language=row.get("language", "c++"),
    )
    return CanonicalizeResult("accepted", record)


def cascade_bucket(size: int) -> str:
    if size <= 1:
        return "1"
    if size <= 5:
        return "2-5"
    if size <= 10:
        return "6-10"
    return ">10"


def to_repair_row(rec: Record) -> dict:
    """Convert a canonical real-corpus Record to run_sweep input format."""
    diag = rec.primary_diagnostic
    detail = rec.provenance.detail
    return {
        "instance_id": rec.record_id,
        "buggy_src": rec.erroneous_src,
        "corrected_src": rec.corrected_src,
        "compile_cmd": detail["compile_cmd"],
        "diag_id": diag.diag_id if diag else None,
        "diag_name": diag.diag_name if diag else None,
        "language": rec.language,
        "cascade_size": detail["cascade_size"],
        "cascade_bucket": cascade_bucket(detail["cascade_size"]),
        "target_diag": detail.get("target_diag"),
        "primary_matches_target": detail.get("primary_matches_target"),
        "generation_label": detail.get("generation_label"),
        "project": rec.provenance.source.split(":", 1)[0],
        "source_path": detail.get("source_path"),
        "region": detail.get("region"),
        "region_type": detail.get("region_type"),
    }


def _write_jsonl(path: Path, rows: Iterable[dict]) -> dict:
    count = 0
    sha = hashlib.sha256()
    with path.open("wb") as stream:
        for row in rows:
            line = (json.dumps(row, sort_keys=True) + "\n").encode()
            stream.write(line)
            sha.update(line)
            count += 1
    return {"path": str(path), "records": count, "bytes": path.stat().st_size,
            "sha256": sha.hexdigest()}


def _distinct_diags(records: Iterable[Record]) -> int:
    return len({r.primary_diagnostic.diag_name for r in records
                if r.primary_diagnostic and r.primary_diagnostic.diag_name})


def _clang_version(clang_bin: str) -> str:
    try:
        result = subprocess.run(
            [clang_bin, "--version"], capture_output=True, text=True, timeout=10
        )
        return result.stdout.splitlines()[0] if result.stdout else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Revalidate flat real-corpus rows, canonicalize, dedup and split."
    )
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--compile-db", type=Path, required=True)
    ap.add_argument("--clang-bin", required=True)
    ap.add_argument("--diagtool-bin", required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--salt", default="fuzzlang-realcorpus-v2")
    ap.add_argument("--dev-fraction", type=float, default=0.1)
    ap.add_argument("--eval-fraction", type=float, default=0.1)
    ap.add_argument("--llvm-revision", default="llvmorg-22.1.8")
    args = ap.parse_args()

    rows = [json.loads(line) for line in args.input.read_text().splitlines()
            if line.strip()]
    db = load_compile_db(args.compile_db)
    print(f"[finalize] indexing {len(db)} compile-DB sources", flush=True)
    source_index = build_corrected_source_index(db)
    verifier = FuzzlangClangVerifier(
        args.clang_bin, args.diagtool_bin, timeout_s=args.timeout
    )

    def work(row: dict) -> CanonicalizeResult:
        return canonicalize_row(row, verifier, source_index=source_index)

    results: list[CanonicalizeResult] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        for index, result in enumerate(executor.map(work, rows), 1):
            results.append(result)
            if index % 200 == 0:
                accepted = sum(r.status == "accepted" for r in results)
                print(f"[finalize] {index}/{len(rows)}; accepted={accepted}",
                      flush=True)

    statuses = Counter(result.status for result in results)
    accepted = [result.record for result in results if result.record is not None]
    deduped = dedup_records(accepted)
    parts = split_records(
        deduped, salt=args.salt, dev_fraction=args.dev_fraction,
        eval_fraction=args.eval_fraction,
    )
    all_records = [record for split in (Split.TRAIN, Split.DEV, Split.EVAL)
                   for record in parts[split]]

    args.out_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, dict] = {}
    files["canonical_all"] = _write_jsonl(
        args.out_dir / "canonical_all.jsonl", (r.to_dict() for r in all_records)
    )
    for split in (Split.TRAIN, Split.DEV, Split.EVAL):
        files[split.value] = _write_jsonl(
            args.out_dir / f"{split.value}.jsonl",
            (r.to_dict() for r in parts[split]),
        )
    files["eval_repair"] = _write_jsonl(
        args.out_dir / "eval.repair.jsonl",
        (to_repair_row(r) for r in parts[Split.EVAL]),
    )
    rejected_rows = (
        {"instance_id": row.get("instance_id"), "status": result.status,
         "detail": result.detail}
        for row, result in zip(rows, results) if result.record is None
    )
    files["rejected"] = _write_jsonl(
        args.out_dir / "rejected.jsonl", rejected_rows
    )

    source_splits: dict[str, set[str]] = defaultdict(set)
    for split, records in parts.items():
        for record in records:
            source_splits[record.provenance.source].add(split.value)
    straddlers = {source: sorted(splits) for source, splits in source_splits.items()
                  if len(splits) > 1}
    input_bytes = args.input.read_bytes()
    manifest = {
        "schema_version": 1,
        "release": "realcorpus-v2",
        "llvm_revision": args.llvm_revision,
        "clang_version": _clang_version(args.clang_bin),
        "clang_bin": args.clang_bin,
        "diagtool_bin": args.diagtool_bin,
        "input": {
            "path": str(args.input), "records": len(rows),
            "bytes": len(input_bytes),
            "sha256": hashlib.sha256(input_bytes).hexdigest(),
        },
        "revalidation": {
            "accepted": len(accepted),
            "rejected": len(rows) - len(accepted),
            "statuses": dict(sorted(statuses.items())),
            "gate": ["corrected_clean", "buggy_fails", "primary_diag_stable",
                     "source_resolved", "source_not_test"],
        },
        "dedup": {
            "before": len(accepted), "after": len(deduped),
            "removed": len(accepted) - len(deduped),
            "key": "primary diagnostic + normalized 5-line error window",
        },
        "corpus": {
            "records": len(deduped), "distinct_diagnostics": _distinct_diags(deduped),
            "sources": len({r.provenance.source for r in deduped}),
            "languages": dict(Counter(r.language for r in deduped)),
            "generation_labels": dict(Counter(
                r.provenance.detail["generation_label"] for r in deduped)),
            "cascade_buckets": dict(Counter(cascade_bucket(
                r.provenance.detail["cascade_size"]) for r in deduped)),
            "test_sources": sum(is_test_path(r.provenance.detail["source_path"])
                                for r in deduped),
        },
        "split": {
            "salt": args.salt,
            "dev_fraction": args.dev_fraction,
            "eval_fraction": args.eval_fraction,
            "provenance_isolation_ok": not straddlers,
            "straddling_sources": straddlers,
            "counts": {
                split.value: {
                    "records": len(parts[split]),
                    "sources": len({r.provenance.source for r in parts[split]}),
                    "distinct_diagnostics": _distinct_diags(parts[split]),
                }
                for split in (Split.TRAIN, Split.DEV, Split.EVAL)
            },
        },
        "files": files,
    }
    manifest_path = args.out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"[finalize] statuses={dict(statuses)}", flush=True)
    print(f"[finalize] accepted={len(accepted)} deduped={len(deduped)}", flush=True)
    print(f"[finalize] split counts="
          f"{ {s.value: len(parts[s]) for s in parts} }", flush=True)
    print(f"[finalize] manifest -> {manifest_path}", flush=True)


if __name__ == "__main__":
    main()
