#!/usr/bin/env python3
"""Turn compiler-verified paired records into one DSL-synthesis request."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from foundation.diagnostics.catalog import load_catalog
from foundation.record import Record
from gen.realcorpus.recipes import minimal_edit


def _window(source: str, start: int, end: int) -> str:
    begin = source.rfind("\n", 0, max(0, start - 240)) + 1
    newline = source.find("\n", min(len(source), max(end, start + 1) + 240))
    finish = len(source) if newline < 0 else newline + 1
    return source[begin:finish].strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--catalog-dir", required=True)
    parser.add_argument("--diag-name", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    entry = load_catalog(args.catalog_dir).by_name.get(args.diag_name)
    if entry is None or not entry.is_error:
        raise ValueError("diag-name must be a catalog error")
    records = [Record.from_dict(json.loads(line)) for line in args.records.read_text().splitlines() if line.strip()]
    selected = [record for record in records if record.primary_diagnostic and record.primary_diagnostic.diag_name == args.diag_name]
    if not selected:
        raise ValueError("no paired exact-target records for diag-name")
    snippets: list[str] = []
    evidence: list[str] = []
    for record in selected[:2]:
        start, old, _new = minimal_edit(record.corrected_src, record.erroneous_src)
        correct = _window(record.corrected_src, start, start + len(old))
        mutated = _window(record.erroneous_src, start, start + len(old))
        snippets.append(correct)
        evidence.append("Correct local code window:\n" + correct + "\nMutated local code window:\n" + mutated)
    while len(snippets) < 2:
        snippets.append(snippets[0])
    request = {
        "diag_name": entry.name, "diag_id": None, "diag_message": entry.message,
        "component": entry.component or "Unknown", "language": selected[0].language,
        "tablegen_definition": f"def {entry.name} : {entry.severity}<{json.dumps(entry.message)}>;",
        "emission_evidence": "\n\n".join(evidence),
        "correct_snippets": snippets,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(request, ensure_ascii=False, sort_keys=True) + "\n")
    print("[record-witness-request] requests=1 uses_llm_api=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
