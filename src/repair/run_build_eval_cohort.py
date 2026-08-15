#!/usr/bin/env python3
"""Draw a fixed, stratified evaluation cohort from a held-out record pool.

Evaluating every held-out record for every arm and seed is not affordable, so
the cohort is subsampled — but it must be subsampled *once*, deterministically,
and identically for every arm, or the comparison stops being paired.

Stratification is by project and language, because the unseen-project column is
dominated by one large C project; an unstratified draw would report a
language-transfer result while calling it a project-transfer result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path


def _rank(record_id: str, seed: int) -> int:
    return int.from_bytes(
        hashlib.sha256(f"{seed}\0{record_id}".encode()).digest()[:8], "big"
    )


def stratified_cohort(rows: list[dict], *, size: int, seed: int) -> list[dict]:
    """Take ``size`` records spread as evenly as possible over (project, language).

    Selection inside a stratum is by hash rank, so the cohort is reproducible
    from the seed alone and does not depend on input order.
    """
    if size <= 0:
        raise ValueError("cohort size must be positive")
    strata: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        key = (row["provenance"]["detail"].get("project", "?"), row.get("language", "?"))
        strata[key].append(row)
    for bucket in strata.values():
        bucket.sort(key=lambda row: _rank(row["record_id"], seed))

    selected: list[dict] = []
    round_index = 0
    keys = sorted(strata)
    while len(selected) < size and any(
        round_index < len(strata[key]) for key in keys
    ):
        for key in keys:
            if len(selected) >= size:
                break
            if round_index < len(strata[key]):
                selected.append(strata[key][round_index])
        round_index += 1
    return sorted(selected, key=lambda row: row["record_id"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--size", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--manifest-out", type=Path)
    args = parser.parse_args()

    rows = [
        json.loads(line)
        for line in args.records.read_text().splitlines() if line.strip()
    ]
    cohort = stratified_cohort(rows, size=args.size, seed=args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in cohort
    ))

    breakdown: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in cohort:
        breakdown[row["provenance"]["detail"].get("project", "?")][row["language"]] += 1
    manifest = {
        "schema": "fuzzlang.eval_cohort.v1",
        "source_records": {
            "path": str(args.records),
            "sha256": hashlib.sha256(args.records.read_bytes()).hexdigest(),
            "records": len(rows),
        },
        "seed": args.seed,
        "requested_size": args.size,
        "cohort_size": len(cohort),
        "stratification": "project x language, hash-ranked within stratum",
        "by_project_language": {
            project: dict(sorted(langs.items()))
            for project, langs in sorted(breakdown.items())
        },
        "diagnostics": len({
            row["provenance"]["detail"]["target_diag"] for row in cohort
        }),
        "source_tus": len({row["provenance"]["source"] for row in cohort}),
    }
    if args.manifest_out is not None:
        args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
        args.manifest_out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
