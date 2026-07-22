#!/usr/bin/env python3
"""Build compiler-witness-backed requests for local FuzzLang Injector synthesis.

Learned recipes are used internally to discover a compiler-confirmed witness.
Their IDs and structured edits are kept solely in the audit JSONL; model-ready
requests contain only TableGen evidence, real correct snippets, and a bounded
compiler-validated witness window.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Iterable

from foundation.diagnostics.catalog import load_catalog
from foundation.verifier import FuzzlangClangVerifier
from gen.fuzzlang_dsl.request_builder import (
    request_to_dict,
    resolve_diag_ids,
)
from gen.fuzzlang_dsl.run_build_requests import (
    _covered_diagnostics,
    _gap_diagnostics,
)
from gen.fuzzlang_dsl.witness_builder import build_witness_synthesis_requests
from gen.realcorpus.clean_source_pool import load_clean_sources_jsonl
from gen.realcorpus.recipes import LearnedRecipe


def _load_recipes(path: Path) -> list[LearnedRecipe]:
    return [
        LearnedRecipe.from_dict(json.loads(line))
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def _write_jsonl(path: Path, rows: Iterable[dict[str, object]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        for row in rows
    )
    path.write_text(encoded)
    return encoded.count("\n")


def _excluded_target_diagnostics(paths: Iterable[Path]) -> set[str]:
    """Load target names from earlier request queues for breadth-first batching."""
    excluded: set[str] = set()
    for path in paths:
        for line_number, line in enumerate(path.read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"{path}:{line_number}: invalid target JSON"
                ) from error
            name = value.get("diag_name") if isinstance(value, dict) else None
            if not isinstance(name, str) or not name:
                raise ValueError(
                    f"{path}:{line_number}: expected non-empty diag_name"
                )
            excluded.add(name)
    return excluded


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipes", type=Path, required=True)
    parser.add_argument("--clean-sources", type=Path, required=True)
    parser.add_argument("--clang-bin", required=True)
    parser.add_argument("--clang-c-bin", required=True)
    parser.add_argument("--diagtool-bin", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--audit-out", type=Path, required=True)
    parser.add_argument("--covered-records", type=Path, action="append", default=[])
    parser.add_argument(
        "--exclude-targets", type=Path, action="append", default=[],
        help="JSONL request queues whose diag_name values are excluded",
    )
    parser.add_argument(
        "--gap-list", type=Path,
        help="optional coverage gap JSONL; only its diagnostic names are eligible",
    )
    parser.add_argument("--max-targets", type=int, required=True)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--snippets-per-target", type=int, default=2)
    parser.add_argument("--snippet-radius", type=int, default=240)
    parser.add_argument("--witness-radius", type=int, default=360)
    parser.add_argument("--max-witness-candidates-per-source", type=int, default=2)
    parser.add_argument("--max-witness-verifications", type=int, default=10_000)
    parser.add_argument(
        "--max-witness-verifications-per-target", type=int,
        help="cap compiler witness attempts spent on one diagnostic target",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.timeout <= 0:
        _parser().error("--timeout must be positive")
    recipes = _load_recipes(args.recipes)
    sources = load_clean_sources_jsonl(args.clean_sources)
    catalog = load_catalog()
    covered = _covered_diagnostics(args.covered_records)
    covered.update(_excluded_target_diagnostics(args.exclude_targets))
    eligible = _gap_diagnostics(args.gap_list)
    verifier = FuzzlangClangVerifier(
        args.clang_bin,
        args.diagtool_bin,
        args.timeout,
        clang_c_bin=args.clang_c_bin,
    )
    result = build_witness_synthesis_requests(
        recipes,
        sources,
        catalog,
        verifier,
        covered_diag_names=covered,
        eligible_diag_names=eligible,
        max_targets=args.max_targets,
        snippets_per_target=args.snippets_per_target,
        snippet_radius=args.snippet_radius,
        witness_radius=args.witness_radius,
        max_witness_candidates_per_source=args.max_witness_candidates_per_source,
        max_witness_verifications=args.max_witness_verifications,
        max_witness_verifications_per_target=(
            args.max_witness_verifications_per_target
        ),
    )
    # Name matching is already exact during witness compilation.  Resolve IDs
    # only after that expensive screening so a 500-target queue does not launch
    # a subprocess for every merely possible recipe diagnostic.
    diag_ids = resolve_diag_ids(
        (item.diag_name for item in result.requests), args.diagtool_bin,
    )
    requests = tuple(
        replace(item, diag_id=diag_ids.get(item.diag_name))
        for item in result.requests
    )
    request_rows = _write_jsonl(args.out, (request_to_dict(item) for item in requests))
    audit_rows = _write_jsonl(args.audit_out, (item.to_dict() for item in result.audits))
    summary = {
        "requests": request_rows,
        "audit_rows": audit_rows,
        "resolved_diag_ids": len(diag_ids),
        "audit_statuses": dict(Counter(item.status for item in result.audits)),
        "witness_verification_usage": dict(result.verification_usage),
        "selection_policy": (
            "portable recipes discover compiler-validated witnesses; recipe edits "
            "and identifiers are audit-only and excluded from model requests"
        ),
        "uses_llm_api": False,
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
