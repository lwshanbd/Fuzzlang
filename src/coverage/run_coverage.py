"""CLI: measure diagnostic coverage of a JSONL dataset of records.

    PYTHONPATH=src python src/coverage/run_coverage.py \
        --records data/dataset.jsonl --target 3 --gap-out data/gap_list.jsonl

Prints the coverage report (covered/total, per-component, gap count) and
optionally writes the gap list (the diagnostics Gen should target next).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from coverage.report import format_report
from coverage.tracker import INVOCATION_COMPONENTS, build_report
from foundation.diagnostics.catalog import load_catalog
from foundation.record import Record


def _load_records(path: Path) -> list[Record]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(Record.from_dict(json.loads(line)))
    return records


def main() -> None:
    ap = argparse.ArgumentParser(description="Measure diagnostic coverage of a dataset.")
    ap.add_argument("--records", type=Path, required=True,
                    help="JSONL of dataset records (Record.to_dict per line)")
    ap.add_argument("--target", type=int, default=3,
                    help="multiplicity target: examples per diagnostic to count as covered")
    ap.add_argument("--gap-out", type=Path, default=None,
                    help="optional JSONL output of the gap list (diagnostics below target)")
    ap.add_argument("--code-only", action="store_true",
                    help="exclude invocation/environment diagnostics (Driver, Frontend, "
                         "Serialization, InstallAPI, CrossTU, Refactoring) that can't be "
                         "single-file broken/corrected code pairs")
    ap.add_argument("--exclude-names", type=Path, default=None,
                    help="file of diagnostic names (one per line) to drop from the "
                         "denominator, e.g. out-of-scope non-C/C++ diagnostics")
    args = ap.parse_args()

    catalog = load_catalog()
    records = _load_records(args.records)
    exclude = INVOCATION_COMPONENTS if args.code_only else None
    exclude_names = None
    if args.exclude_names:
        exclude_names = {l.strip() for l in
                         args.exclude_names.read_text().splitlines() if l.strip()}
    report = build_report(records, catalog, multiplicity_target=args.target,
                          exclude_components=exclude, exclude_names=exclude_names)

    if args.code_only:
        print(f"[coverage] code-only: excluding {', '.join(sorted(INVOCATION_COMPONENTS))}")
    if exclude_names:
        print(f"[coverage] excluding {len(exclude_names)} named diagnostics")
    print(format_report(report))

    if args.gap_out:
        with args.gap_out.open("w", encoding="utf-8") as f:
            for name, count in report.gap_list():
                f.write(json.dumps({
                    "diag_name": name,
                    "count": count,
                    "component": report.component_of.get(name),
                }) + "\n")
        print(f"[coverage] gap list -> {args.gap_out} ({len(report.gap_list())} diagnostics)")


if __name__ == "__main__":
    main()
