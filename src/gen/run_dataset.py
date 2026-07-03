"""CLI: assemble the Gen dataset — dedup + provenance-isolated train/dev/eval.

    PYTHONPATH=src python3 src/gen/run_dataset.py \
        --records data/gen/all.jsonl --out-dir data/gen/splits \
        --salt fuzzlang-gen-v1 --dev-fraction 0.1 --eval-fraction 0.1

Reads verified records, drops structural duplicates, carves provenance-isolated
splits (all records of one provenance source stay together), writes one JSONL
per split plus a committable manifest.json (counts, dedup stats, per-split
diagnostic coverage, isolation audit).
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from foundation.record import Record, Split
from gen.dataset import dedup_records, split_records


def _load(path: Path) -> list[Record]:
    return [Record.from_dict(json.loads(l)) for l in
            path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _distinct_diags(records: list[Record]) -> int:
    return len({r.primary_diagnostic.diag_name for r in records
                if r.primary_diagnostic and r.primary_diagnostic.diag_name})


def main() -> None:
    ap = argparse.ArgumentParser(description="Dedup + split the Gen dataset.")
    ap.add_argument("--records", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, default=Path("data/gen/splits"))
    ap.add_argument("--salt", default="fuzzlang-gen-v1")
    ap.add_argument("--dev-fraction", type=float, default=0.1)
    ap.add_argument("--eval-fraction", type=float, default=0.1)
    args = ap.parse_args()

    raw = _load(args.records)
    deduped = dedup_records(raw)
    parts = split_records(deduped, salt=args.salt,
                          dev_fraction=args.dev_fraction,
                          eval_fraction=args.eval_fraction)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for split, recs in parts.items():
        p = args.out_dir / f"{split.value}.jsonl"
        with p.open("w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r.to_dict()) + "\n")
        files[split.value] = str(p)

    # Isolation audit: no provenance source appears in more than one split.
    src_splits: dict[str, set[str]] = {}
    for split, recs in parts.items():
        for r in recs:
            src_splits.setdefault(r.provenance.source, set()).add(split.value)
    straddlers = {s: sorted(v) for s, v in src_splits.items() if len(v) > 1}

    manifest = {
        "schema_version": 1,
        "salt": args.salt,
        "input_records": len(raw),
        "after_dedup": len(deduped),
        "duplicates_removed": len(raw) - len(deduped),
        "splits": {
            split.value: {
                "records": len(recs),
                "distinct_diagnostics": _distinct_diags(recs),
                "sources": len({r.provenance.source for r in recs}),
                "by_origin": dict(Counter(r.provenance.origin.value for r in recs)),
            }
            for split, recs in parts.items()
        },
        "isolation_ok": not straddlers,
        "straddling_sources": straddlers,
        "outputs": files,
    }
    (args.out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True))

    print(f"[dataset] {len(raw)} records -> {len(deduped)} after dedup "
          f"({manifest['duplicates_removed']} removed)")
    for split in (Split.TRAIN, Split.DEV, Split.EVAL):
        s = manifest["splits"][split.value]
        print(f"  {split.value:5} {s['records']:>6} records, "
              f"{s['distinct_diagnostics']:>4} distinct diagnostics")
    print(f"[dataset] provenance isolation: {'OK' if manifest['isolation_ok'] else 'FAIL'}")
    print(f"[dataset] manifest -> {args.out_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()
