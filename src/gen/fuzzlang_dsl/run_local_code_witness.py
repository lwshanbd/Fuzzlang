#!/usr/bin/env python3
"""Use local Gemma to propose compiler-validated seed witness edits."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Iterable

from foundation.record import Origin, Provenance, Record, Split
from foundation.verifier import FuzzlangClangVerifier
from gen.fuzzlang_dsl.code_witness import (
    CodeWitnessRequest, apply_code_witness_patch, build_code_witness_messages,
    parse_code_witness_patch,
)
from gen.fuzzlang_dsl.local_gemma import (
    DEFAULT_GEMMA_31B_MODEL, DEFAULT_GEMMA_31B_REVISION,
    DEFAULT_GEMMA_31B_SNAPSHOT, LocalGemma31BBackend,
)
from gen.fuzzlang_dsl.injector import FuzzLangInjector
from gen.realcorpus.recipes import extract_recipe


def _load(path: Path) -> list[CodeWitnessRequest]:
    return [CodeWitnessRequest.from_dict(json.loads(line)) for line in path.read_text().splitlines() if line.strip()]


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def load_excluded_injector_ids(paths: Iterable[Path]) -> tuple[str, ...]:
    """Load canonical Injector identities produced by prior campaigns."""
    identities: set[str] = set()
    for path in paths:
        for line in path.read_text().splitlines():
            if line.strip():
                identities.add(FuzzLangInjector.from_dict(json.loads(line)).injector_id)
    return tuple(sorted(identities))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--clang-bin", required=True)
    parser.add_argument("--clang-c-bin", required=True)
    parser.add_argument("--diagtool-bin", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--exclude-injectors", type=Path, action="append", default=[],
        help="canonical Injector JSONL whose identities must not be re-emitted",
    )
    parser.add_argument("--candidates", type=int, default=4)
    parser.add_argument("--temperature", type=float, default=0.5)
    parser.add_argument("--max-tokens", type=int, default=400)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    if args.candidates <= 0 or args.max_tokens <= 0 or args.timeout <= 0:
        parser.error("candidate, token, and timeout bounds must be positive")
    requests = _load(args.requests)
    excluded_injector_ids = frozenset(load_excluded_injector_ids(args.exclude_injectors))
    backend = LocalGemma31BBackend(DEFAULT_GEMMA_31B_SNAPSHOT, seed=args.seed)
    verifier = FuzzlangClangVerifier(args.clang_bin, args.diagtool_bin, args.timeout, clang_c_bin=args.clang_c_bin)
    attempts: list[dict] = []
    records: list[dict] = []
    injectors: dict[str, dict] = {}
    duplicate_existing_injector_candidates = 0
    for request_index, request in enumerate(requests):
        baseline = verifier.verify(request.corrected_src, list(request.compile_cmd), logical_path=request.source_path)
        if not baseline.ok:
            attempts.append({"request_index": request_index, "diag_name": request.diag_name, "status": "baseline_not_clean"})
            continue
        responses = backend.chat(messages=build_code_witness_messages(request), temperature=args.temperature, max_tokens=args.max_tokens, n=args.candidates)
        for candidate_index, response in enumerate(responses):
            patch, reason = parse_code_witness_patch(response.text, request)
            row = {"request_index": request_index, "diag_name": request.diag_name, "candidate_index": candidate_index, "output_tokens": response.output_tokens, "reason": reason}
            if patch is None:
                row["status"] = "rejected"
                attempts.append(row)
                continue
            erroneous = apply_code_witness_patch(request, patch)
            verified = verifier.verify(erroneous, list(request.compile_cmd), logical_path=request.source_path)
            if verified.ok or verified.diag is None or verified.diag.diag_name != request.diag_name:
                row["status"] = "rejected"
                row["reason"] = "candidate_clean_or_wrong_primary"
                row["observed_diag"] = verified.diag.diag_name if verified.diag else None
                attempts.append(row)
                continue
            record_id = "code-witness-" + hashlib.sha256((request.source_id + "\0" + erroneous).encode()).hexdigest()[:24]
            record = Record(
                record_id=record_id, erroneous_src=erroneous, corrected_src=request.corrected_src,
                diagnostics=(verified.diag,), split=Split.TRAIN, language=request.language,
                provenance=Provenance(origin=Origin.MUTATE, source=request.source_id, detail={
                    "strategy": "gemma_code_witness_bootstrap", "project": request.project,
                    "source_path": request.source_path, "compile_cmd": list(request.compile_cmd),
                    "target_diag": request.diag_name, "primary_matches_target": True,
                }),
            )
            recipe = extract_recipe(record, context_tokens=2, allow_fresh_identifiers=True, allow_literal_payloads=True, normalize_token_edits=True)
            if recipe is not None and recipe.portable:
                injector = FuzzLangInjector.from_recipe(recipe, diag_id=verified.diag.diag_id)
                if injector.injector_id in excluded_injector_ids:
                    row["injector_status"] = "duplicate_excluded_injector"
                    duplicate_existing_injector_candidates += 1
                else:
                    injectors[injector.injector_id] = injector.to_dict()
            row["status"] = "exact_target"
            row["record_id"] = record.record_id
            attempts.append(row)
            records.append(record.to_dict())
    _write(args.output_dir / "attempts.jsonl", attempts)
    _write(args.output_dir / "records.jsonl", records)
    _write(args.output_dir / "injectors.jsonl", list(injectors.values()))
    manifest = {"schema": "fuzzlang.code_witness_bootstrap", "model": {"name": DEFAULT_GEMMA_31B_MODEL, "revision": DEFAULT_GEMMA_31B_REVISION, "parameters": "31B"}, "paid_api_calls": False, "counts": {"requests": len(requests), "attempts": len(attempts), "records": len(records), "portable_injectors": len(injectors), "excluded_injector_identities": len(excluded_injector_ids), "duplicate_existing_injector_candidates": duplicate_existing_injector_candidates}}
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")
    print(json.dumps(manifest["counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
