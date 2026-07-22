#!/usr/bin/env python3
"""Reorder a clean-source pool so compiler witness sources are replayed first."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gen.fuzzlang_dsl.witness_sources import prioritize_witness_sources
from gen.realcorpus.clean_source_pool import load_clean_sources_jsonl


def _load_audit(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{line_number}: invalid audit JSON") from error
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: audit row must be an object")
        rows.append(value)
    return rows


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean-sources", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = prioritize_witness_sources(
        load_clean_sources_jsonl(args.clean_sources),
        _load_audit(args.audit),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(
        json.dumps(source.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
        for source in result.sources
    ))
    print(json.dumps({
        "sources": len(result.sources),
        "prioritized_witness_sources": len(result.prioritized_source_ids),
        "missing_witness_sources": len(result.missing_witness_source_ids),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
