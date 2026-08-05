#!/usr/bin/env python3
"""Export an auditable Injector-to-diagnostic inventory and gap list as CSV.

The input strict audit names every Injector JSONL file it used, so this exporter
does not guess which experimental artifacts are authoritative.  It emits only
metadata: no dataset source, Clang regression-test source, or Injector payload
is copied into the CSVs.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Iterable

from foundation.diagnostics.catalog import Catalog, load_catalog
from gen.fuzzlang_dsl.injector import FuzzLangInjector


def _read_names(paths: Iterable[Path]) -> set[str]:
    names: set[str] = set()
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            name = line.strip()
            if name and not name.startswith("#"):
                names.add(name)
    return names


def _load_portable_injectors(paths: Iterable[Path]) -> list[FuzzLangInjector]:
    by_id: dict[str, FuzzLangInjector] = {}
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            injector = FuzzLangInjector.from_json(line)
            if injector.portable:
                by_id.setdefault(injector.injector_id, injector)
    return sorted(by_id.values(), key=lambda item: (
        item.target_diag, item.language, item.operation, item.injector_id,
    ))


def _write_csv(path: Path, fields: list[str], rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _bool(value: bool) -> str:
    return "true" if value else "false"


def export_inventory(
    *,
    audit: dict,
    catalog: Catalog,
    test_reachable: set[str],
    emission_context_names: set[str],
) -> tuple[
    list[dict[str, str]],
    list[dict[str, str]],
    list[dict[str, str]],
    list[dict[str, str]],
]:
    """Return Injector mapping, per-diagnostic index, gaps, and summary rows."""
    injector_paths = [Path(path) for path in audit["inputs"]["injector_files"]]
    injectors = _load_portable_injectors(injector_paths)
    covered = set(audit["verified_diagnostic_names"])
    catalog_errors = {entry.name: entry for entry in catalog.errors()}

    inventory_rows = [{
        "injector_id": injector.injector_id,
        "diagnostic_name": injector.target_diag,
        "diagnostic_id": "" if injector.target_diag_id is None else str(injector.target_diag_id),
        "language": injector.language,
        "operation": injector.operation,
        "schema_version": str(injector.schema_version),
        "source_recipe_id": injector.source_recipe_id or "",
        "support": str(injector.support),
        "target_is_catalog_error": _bool(injector.target_diag in catalog_errors),
        "strict_diagnostic_covered": _bool(injector.target_diag in covered),
    } for injector in injectors]
    by_diagnostic: dict[str, list[FuzzLangInjector]] = {}
    for injector in injectors:
        by_diagnostic.setdefault(injector.target_diag, []).append(injector)
    diagnostic_rows = [{
        "diagnostic_name": name,
        "diagnostic_id": ";".join(sorted({
            str(injector.target_diag_id)
            for injector in diagnostic_injectors
            if injector.target_diag_id is not None
        })),
        "component": (catalog_errors[name].component or "")
        if name in catalog_errors else "",
        "portable_injector_count": str(len(diagnostic_injectors)),
        "languages": ";".join(sorted({
            injector.language for injector in diagnostic_injectors
        })),
        "operations": ";".join(sorted({
            injector.operation for injector in diagnostic_injectors
        })),
        "target_is_catalog_error": _bool(name in catalog_errors),
        "strict_diagnostic_covered": _bool(name in covered),
    } for name, diagnostic_injectors in sorted(by_diagnostic.items())]
    uncovered_rows = [{
        "diagnostic_name": entry.name,
        "component": entry.component or "",
        "tablegen_message": entry.message,
        "test_reachable": _bool(entry.name in test_reachable),
        "emission_context_available": _bool(entry.name in emission_context_names),
    } for entry in sorted(catalog.errors(), key=lambda item: item.name)
        if entry.name not in covered]
    summary_rows = [
        {"metric": "catalog_error_diagnostic_types", "value": str(len(catalog_errors))},
        {"metric": "strict_verified_diagnostic_types", "value": str(len(covered))},
        {"metric": "unique_portable_injectors", "value": str(len(injectors))},
        {"metric": "injector_target_diagnostic_types", "value": str(len(diagnostic_rows))},
        {"metric": "injector_targets_not_strictly_verified", "value": str(sum(
            row["strict_diagnostic_covered"] == "false" for row in diagnostic_rows
        ))},
        {"metric": "uncovered_catalog_error_types", "value": str(len(uncovered_rows))},
        {"metric": "test_reachable_catalog_error_types", "value": str(len(test_reachable & set(catalog_errors)))},
        {"metric": "test_reachable_strict_overlap", "value": str(len(test_reachable & covered))},
        {"metric": "strict_fuzzlang_only_types", "value": str(len(covered - test_reachable))},
        {"metric": "test_reachable_uncovered_types", "value": str(sum(
            row["test_reachable"] == "true" for row in uncovered_rows
        ))},
    ]
    return inventory_rows, diagnostic_rows, uncovered_rows, summary_rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--catalog-dir", type=Path,
                        default=Path("external/llvm-project/clang/include/clang/Basic"))
    parser.add_argument("--test-reachable", type=Path, action="append", default=[])
    parser.add_argument("--emission-index", type=Path)
    parser.add_argument("--injector-out", type=Path, required=True)
    parser.add_argument("--diagnostic-out", type=Path, required=True)
    parser.add_argument("--uncovered-out", type=Path, required=True)
    parser.add_argument("--summary-out", type=Path, required=True)
    args = parser.parse_args()

    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    if not isinstance(audit.get("inputs", {}).get("injector_files"), list):
        parser.error("audit must contain inputs.injector_files")
    if not isinstance(audit.get("verified_diagnostic_names"), list):
        parser.error("audit must contain verified_diagnostic_names")
    emission_context_names: set[str] = set()
    if args.emission_index is not None:
        index = json.loads(args.emission_index.read_text(encoding="utf-8"))
        diagnostics = index.get("diagnostics", {})
        if not isinstance(diagnostics, dict):
            parser.error("emission index must contain a diagnostics object")
        emission_context_names = set(diagnostics)
    inventory_rows, diagnostic_rows, uncovered_rows, summary_rows = export_inventory(
        audit=audit,
        catalog=load_catalog(args.catalog_dir),
        test_reachable=_read_names(args.test_reachable),
        emission_context_names=emission_context_names,
    )
    _write_csv(args.injector_out, list(inventory_rows[0]) if inventory_rows else [
        "injector_id", "diagnostic_name", "diagnostic_id", "language", "operation",
        "schema_version", "source_recipe_id", "support", "target_is_catalog_error",
        "strict_diagnostic_covered",
    ], inventory_rows)
    _write_csv(args.diagnostic_out, [
        "diagnostic_name", "diagnostic_id", "component",
        "portable_injector_count", "languages", "operations",
        "target_is_catalog_error", "strict_diagnostic_covered",
    ], diagnostic_rows)
    _write_csv(args.uncovered_out, [
        "diagnostic_name", "component", "tablegen_message", "test_reachable",
        "emission_context_available",
    ], uncovered_rows)
    _write_csv(args.summary_out, ["metric", "value"], summary_rows)
    print(json.dumps({
        "injectors": len(inventory_rows),
        "injector_target_diagnostics": len(diagnostic_rows),
        "uncovered_errors": len(uncovered_rows),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
