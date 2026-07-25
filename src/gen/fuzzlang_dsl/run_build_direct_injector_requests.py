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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--witness-requests", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--snippets-per-target", type=int, default=2)
    args = parser.parse_args()
    witnesses = tuple(
        CodeWitnessRequest.from_dict(json.loads(line))
        for line in args.witness_requests.read_text().splitlines()
        if line.strip()
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
