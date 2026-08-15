#!/usr/bin/env python3
"""Build a compact verified-source pool for a batch of target Injectors.

The witness file is only a routing index: output rows always come from the
canonical CleanSourceTU pool, not from Clang tests or copied test snippets.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from gen.fuzzlang_dsl.campaign import load_injectors_jsonl
from gen.realcorpus.clean_source_pool import load_clean_sources_jsonl


def routed_sources(
    injector_path: Path,
    witness_path: Path,
    pool_path: Path,
    *,
    shard_count: int = 1,
    shard_index: int = 0,
):
    """Return source-pool rows needed by the Injector targets, in pool order."""
    if shard_count <= 0:
        raise ValueError("shard_count must be positive")
    if not 0 <= shard_index < shard_count:
        raise ValueError("shard_index must satisfy 0 <= shard_index < shard_count")
    injectors = load_injectors_jsonl(injector_path)
    targets = {
        item.target_diag for item in injectors[shard_index::shard_count]
    }
    witness_ids: dict[str, set[str]] = {}
    for line in witness_path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        name, source_id = row["diag_name"], row["source_id"]
        if name in targets:
            witness_ids.setdefault(name, set()).add(source_id)
    missing = sorted(targets - set(witness_ids))
    if missing:
        raise ValueError("no witness source for Injector targets: " + ", ".join(missing))
    wanted = set().union(*witness_ids.values())
    sources = load_clean_sources_jsonl(pool_path)
    selected = [source for source in sources if source.source_id in wanted]
    found = {source.source_id for source in selected}
    absent = sorted(wanted - found)
    if absent:
        raise ValueError("witness source absent from canonical pool: " + ", ".join(absent))
    return selected


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--injectors", required=True)
    parser.add_argument("--witnesses", required=True)
    parser.add_argument("--clean-sources", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    args = parser.parse_args(argv)
    selected = routed_sources(
        Path(args.injectors),
        Path(args.witnesses),
        Path(args.clean_sources),
        shard_count=args.shard_count,
        shard_index=args.shard_index,
    )
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(item.to_dict(), sort_keys=True) + "\n" for item in selected))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
