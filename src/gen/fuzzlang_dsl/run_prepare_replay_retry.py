#!/usr/bin/env python3
"""Prepare local synthesis retries from compiler replay feedback."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from gen.fuzzlang_dsl.retry import (
    build_near_miss_witness_evidence,
    load_json_rows,
    select_replay_retry_requests,
)
from gen.realcorpus.clean_source_pool import load_clean_sources_jsonl


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _write_jsonl(path: Path, values: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(_canonical_json(value) + "\n" for value in values)
    path.write_text(payload)
    return payload.count("\n")


def _file_info(path: Path, *, rows: int | None = None) -> dict[str, Any]:
    payload = path.read_bytes()
    value: dict[str, Any] = {
        "path": str(path),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    if rows is not None:
        value["records"] = rows
    return value


def _load_manifest(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"campaign manifest must be a JSON object: {path}")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--injectors", type=Path, required=True)
    parser.add_argument(
        "--campaign-manifest", type=Path, action="append", required=True,
        help="replay manifest; repeat for sharded campaigns",
    )
    parser.add_argument(
        "--rejections", type=Path, action="append", required=True,
        help="replay rejections JSONL; repeat for sharded campaigns",
    )
    parser.add_argument(
        "--clean-sources", type=Path,
        help=(
            "optional verified CleanSourceTU JSONL used to reconstruct one "
            "correct/mutated near-miss window per replayed Injector"
        ),
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--manifest-out", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output_paths = {args.out.resolve(), args.manifest_out.resolve()}
    if len(output_paths) != 2:
        raise ValueError("out and manifest-out must be distinct")
    input_paths = {
        args.requests.resolve(), args.injectors.resolve(),
        *(path.resolve() for path in args.campaign_manifest),
        *(path.resolve() for path in args.rejections),
    }
    if args.clean_sources is not None:
        input_paths.add(args.clean_sources.resolve())
    if output_paths & input_paths:
        raise ValueError("replay retry outputs must not overwrite inputs")

    requests = load_json_rows(args.requests)
    injectors = load_json_rows(args.injectors)
    campaigns = [_load_manifest(path) for path in args.campaign_manifest]
    rejections = [
        row for path in args.rejections for row in load_json_rows(path)
    ]
    clean_sources = (
        load_clean_sources_jsonl(args.clean_sources)
        if args.clean_sources is not None else []
    )
    near_miss_evidence = (
        build_near_miss_witness_evidence(injectors, clean_sources, rejections)
        if args.clean_sources is not None else {}
    )
    selected, summary = select_replay_retry_requests(
        requests,
        injectors,
        campaigns,
        rejections,
        near_miss_evidence_by_injector=near_miss_evidence,
    )
    rows = _write_jsonl(args.out, selected)
    manifest = {
        "schema": "fuzzlang.replay_retry_selection",
        "schema_version": 1,
        "uses_llm_api": False,
        "selection": summary,
        "inputs": {
            "requests": _file_info(args.requests, rows=len(requests)),
            "injectors": _file_info(args.injectors, rows=len(injectors)),
            "campaign_manifests": [
                _file_info(path) for path in args.campaign_manifest
            ],
            "rejections": [
                _file_info(path, rows=len(load_json_rows(path)))
                for path in args.rejections
            ],
            **(
                {"clean_sources": _file_info(
                    args.clean_sources, rows=len(clean_sources),
                )}
                if args.clean_sources is not None else {}
            ),
        },
        "near_miss_witnesses": len(near_miss_evidence),
        "outputs": {"requests": _file_info(args.out, rows=rows)},
    }
    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_out.write_text(_canonical_json(manifest) + "\n")
    print(f"[prepare-replay-retry] requests={rows} uses_llm_api=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
