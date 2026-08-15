#!/usr/bin/env python3
"""Build direct-Injector synthesis requests from grouped real-code windows."""
from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from gen.fuzzlang_dsl.code_witness import (
    CodeWitnessRequest, build_direct_injector_requests,
)
from gen.fuzzlang_dsl.synthesis import DiagnosticEvidence, SynthesisRequest
from gen.fuzzlang_dsl.regression_evidence import (
    has_regression_test_source_evidence,
    has_regression_trigger_evidence,
    regression_evidence_for,
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


def add_regression_trigger_evidence(
    requests: tuple[SynthesisRequest, ...], *, test_root: Path | None,
) -> tuple[SynthesisRequest, ...]:
    """Append test-derived trigger context as prompt-only evidence.

    Regression tests are never sources of a generated record.  Their bounded
    snippets merely help the model infer the target diagnostic precondition;
    replay is still restricted to real clean source TUs.
    """
    if test_root is None:
        return requests
    enriched: list[SynthesisRequest] = []
    for request in requests:
        existing = request.evidence.emission_evidence
        if has_regression_test_source_evidence(existing):
            enriched.append(request)
            continue
        regression = regression_evidence_for(request.diag_message, test_root)
        if regression is None:
            enriched.append(request)
            continue
        evidence = regression if existing is None else existing + "\n\n" + regression
        enriched.append(replace(
            request,
            evidence=DiagnosticEvidence(
                tablegen_definition=request.evidence.tablegen_definition,
                emission_evidence=evidence,
            ),
        ))
    return tuple(enriched)


def filter_regression_evidenced_requests(
    requests: tuple[SynthesisRequest, ...],
) -> tuple[SynthesisRequest, ...]:
    """Retain only direct requests backed by prompt-only Clang test evidence."""
    return tuple(
        request for request in requests
        if has_regression_trigger_evidence(request.evidence.emission_evidence)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--witness-requests", type=Path, action="append", required=True,
        help="Code-witness request JSONL; repeat to pool real windows across batches",
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--snippets-per-target", type=int, default=2)
    parser.add_argument(
        "--allow-single-witness", action="store_true",
        help=(
            "permit one clean real-source witness only for an explicitly "
            "profile-constrained long-tail Injector request"
        ),
    )
    parser.add_argument(
        "--diag-name", action="append",
        help="restrict synthesis to this target diagnostic; repeatable",
    )
    parser.add_argument(
        "--regression-test-root", type=Path,
        help=(
            "optional Clang test root used only for bounded prompt evidence; "
            "never as a generated-record source"
        ),
    )
    parser.add_argument(
        "--require-regression-test-evidence", action="store_true",
        help=(
            "emit only requests with Clang-test trigger evidence; tests remain "
            "prompt-only evidence and never generated-record sources"
        ),
    )
    args = parser.parse_args()
    requested_names = frozenset(args.diag_name or ())
    witnesses = load_selected_witnesses(
        args.witness_requests, diagnostic_names=requested_names,
    )
    requests = add_regression_trigger_evidence(
        build_direct_injector_requests(
            witnesses,
            snippets_per_target=args.snippets_per_target,
            allow_single_witness=args.allow_single_witness,
        ),
        test_root=args.regression_test_root,
    )
    if args.require_regression_test_evidence:
        requests = filter_regression_evidenced_requests(requests)
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
