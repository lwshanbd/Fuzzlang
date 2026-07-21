#!/usr/bin/env python3
"""Build real-code/compiler-evidence requests for local Injector synthesis.

Portable archived recipes only retrieve matching clean production snippets.
They are never sent to the model and never become output Injectors directly.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from typing import Iterable

from foundation.diagnostics.catalog import load_catalog
from foundation.record import Record
from gen.fuzzlang_dsl.request_builder import (
    build_synthesis_requests,
    request_to_dict,
    resolve_diag_ids,
)
from gen.realcorpus.clean_source_pool import load_clean_sources_jsonl
from gen.realcorpus.recipes import LearnedRecipe


def _load_recipes(path: Path) -> list[LearnedRecipe]:
    return [
        LearnedRecipe.from_dict(json.loads(line))
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def _covered_diagnostics(paths: Iterable[Path]) -> set[str]:
    covered: set[str] = set()
    for path in paths:
        for line in path.read_text().splitlines():
            if line.strip():
                record = Record.from_dict(json.loads(line))
                covered.add(record.primary_diagnostic.diag_name)
    return covered


def _gap_diagnostics(path: Path | None) -> set[str] | None:
    if path is None:
        return None
    return {
        value["diag_name"]
        for line in path.read_text().splitlines()
        if line.strip()
        for value in [json.loads(line)]
    }


def _write_jsonl(path: Path, rows: Iterable[dict[str, object]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        for row in rows
    )
    path.write_text(encoded)
    return encoded.count("\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipes", type=Path, required=True)
    parser.add_argument("--clean-sources", type=Path, required=True)
    parser.add_argument("--diagtool-bin", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--audit-out", type=Path, required=True)
    parser.add_argument("--covered-records", type=Path, action="append", default=[])
    parser.add_argument(
        "--gap-list", type=Path,
        help="optional coverage gap JSONL; only its diagnostic names are eligible",
    )
    parser.add_argument("--max-targets", type=int, required=True)
    parser.add_argument("--snippets-per-target", type=int, default=2)
    parser.add_argument("--snippet-radius", type=int, default=240)
    return parser


def main() -> int:
    args = _parser().parse_args()
    recipes = _load_recipes(args.recipes)
    sources = load_clean_sources_jsonl(args.clean_sources)
    catalog = load_catalog()
    result = build_synthesis_requests(
        recipes,
        sources,
        catalog,
        covered_diag_names=_covered_diagnostics(args.covered_records),
        eligible_diag_names=_gap_diagnostics(args.gap_list),
        max_targets=args.max_targets,
        snippets_per_target=args.snippets_per_target,
        snippet_radius=args.snippet_radius,
    )
    # Resolve only the bounded selected set; probing every catalog/recipe name
    # would turn request construction into thousands of needless subprocesses.
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
        "selection_policy": (
            "catalog error gaps ranked by portable recipe support; recipes are "
            "retrieval-only and are not included in model prompts"
        ),
        "uses_llm_api": False,
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
