#!/usr/bin/env python3
"""Merge synthesized Injector JSONL artifacts by stable Injector identity."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, Sequence

from gen.fuzzlang_dsl.campaign import load_injectors_jsonl
from gen.fuzzlang_dsl.injector import FuzzLangInjector


def merge_injectors(paths: Iterable[Path]) -> list[FuzzLangInjector]:
    """Return input-order-first unique Injector rows, rejecting ID collisions."""
    result: list[FuzzLangInjector] = []
    by_id: dict[str, FuzzLangInjector] = {}
    for path in paths:
        for injector in load_injectors_jsonl(path):
            prior = by_id.get(injector.injector_id)
            if prior is None:
                by_id[injector.injector_id] = injector
                result.append(injector)
            elif prior != injector:
                raise ValueError(f"Injector ID collision with distinct content: {injector.injector_id}")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--glob", required=True, help="glob relative to --root")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    paths = sorted(args.root.glob(args.glob))
    if not paths:
        raise ValueError("--glob matched no Injector artifacts")
    injectors = merge_injectors(paths)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(item.to_json() + "\n" for item in injectors))
    print(f"[merge-injectors] inputs={len(paths)} injectors={len(injectors)} targets={len({item.target_diag for item in injectors})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
