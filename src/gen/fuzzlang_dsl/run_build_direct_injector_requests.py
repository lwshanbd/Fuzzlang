#!/usr/bin/env python3
"""Build direct-Injector synthesis requests from grouped real-code windows."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gen.fuzzlang_dsl.code_witness import (
    CodeWitnessRequest, build_direct_injector_requests,
)
from gen.fuzzlang_dsl.request_builder import request_to_dict


def load_selected_witnesses(
    paths: list[Path], *, diagnostic_names: set[str] | frozenset[str],
) -> tuple[CodeWitnessRequest, ...]:
    """Pool request files while retaining only explicitly selected targets."""
    witnesses: list[CodeWitnessRequest] = []
    for path in paths:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            if diagnostic_names and value.get("diag_name") not in diagnostic_names:
                continue
            witnesses.append(CodeWitnessRequest.from_dict(value))
    return tuple(witnesses)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--witness-requests", type=Path, action="append", required=True,
        help="Code-witness request JSONL; repeat to pool real windows across batches",
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--snippets-per-target", type=int, default=2)
    parser.add_argument(
        "--diag-name", action="append",
        help="restrict synthesis to this target diagnostic; repeatable",
    )
    args = parser.parse_args()
    requested_names = frozenset(args.diag_name or ())
    witnesses = load_selected_witnesses(
        args.witness_requests, diagnostic_names=requested_names,
    )
    requests = build_direct_injector_requests(
        witnesses, snippets_per_target=args.snippets_per_target,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(
        json.dumps(request_to_dict(request), ensure_ascii=False, sort_keys=True)
        + "\n"
        for request in requests
    ))
    print(json.dumps({"requests": len(requests), "uses_llm_api": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
