#!/usr/bin/env python3
"""Extract un-emitted FuzzLang DSL context variants from verified seed records."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from foundation.record import Record
from gen.fuzzlang_dsl.context_variants import (
    DEFAULT_RECIPE_CONTEXT_TOKENS,
    extract_contextual_injectors,
    load_excluded_injector_ids,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
    ))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--manifest-out", type=Path, required=True)
    parser.add_argument(
        "--diagnostic-name",
        action="append",
        default=[],
        help="retain only records whose primary diagnostic has this name",
    )
    parser.add_argument("--exclude-injectors", type=Path, action="append", default=[])
    parser.add_argument("--recipe-context-tokens", type=int, action="append", default=None)
    parser.add_argument(
        "--preserve-inserted-identifier-spellings",
        action="store_true",
        help="emit literal-name variants for identifiers introduced by the edit",
    )
    parser.add_argument(
        "--omit-recorded-diag-id",
        action="store_true",
        help=(
            "leave target DiagID unset so replay binds the Injector solely by "
            "diagnostic name under the current compiler build"
        ),
    )
    args = parser.parse_args()
    context_tokens = tuple(
        args.recipe_context_tokens
        if args.recipe_context_tokens is not None
        else DEFAULT_RECIPE_CONTEXT_TOKENS
    )
    if any(level < 0 for level in context_tokens):
        parser.error("recipe context levels must be non-negative")
    excluded = frozenset(load_excluded_injector_ids(args.exclude_injectors))
    records = [
        Record.from_dict(json.loads(line))
        for line in args.records.read_text().splitlines() if line.strip()
    ]
    selected_diagnostics = frozenset(args.diagnostic_name)
    if selected_diagnostics:
        records = [
            record for record in records
            if (
                record.primary_diagnostic is not None
                and record.primary_diagnostic.diag_name in selected_diagnostics
            )
        ]
    injectors: dict[str, dict] = {}
    for record in records:
        diagnostic = record.primary_diagnostic
        if diagnostic is None:
            continue
        for injector in extract_contextual_injectors(
            record,
            diag_id=None if args.omit_recorded_diag_id else diagnostic.diag_id,
            context_tokens=context_tokens,
            preserve_inserted_identifier_spellings=(
                args.preserve_inserted_identifier_spellings
            ),
        ):
            if injector.injector_id not in excluded:
                injectors[injector.injector_id] = injector.to_dict()
    _write_jsonl(args.out, list(injectors.values()))
    manifest = {
        "schema": "fuzzlang.context_variant_extraction",
        "schema_version": 1,
        "recipe_context_tokens": list(context_tokens),
        "preserve_inserted_identifier_spellings": (
            args.preserve_inserted_identifier_spellings
        ),
        "omit_recorded_diag_id": args.omit_recorded_diag_id,
        "counts": {
            "input_records": sum(
                1 for line in args.records.read_text().splitlines() if line.strip()
            ),
            "selected_records": len(records),
            "excluded_injectors": len(excluded),
            "emitted_injectors": len(injectors),
        },
        "selected_diagnostics": sorted(selected_diagnostics),
    }
    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_out.write_text(json.dumps(manifest, sort_keys=True) + "\n")
    print(json.dumps(manifest["counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
