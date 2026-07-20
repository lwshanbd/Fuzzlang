#!/usr/bin/env python3
"""CLI release gate from legacy Stage-2 NatErr JSONL to canonical Records."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Callable, Sequence

from foundation.verifier import FuzzlangClangVerifier
from real.formalize_naterr import SourceAt, formalize_row, git_source_at


VerifierFactory = Callable[[str, str, float], object]


def _make_verifier(clang_bin: str, diagtool_bin: str, timeout: float):
    return FuzzlangClangVerifier(clang_bin, diagtool_bin, timeout_s=timeout)


def _safe_outputs(input_path: Path, outputs: Sequence[Path]) -> bool:
    resolved_input = input_path.resolve()
    resolved_outputs = [path.resolve() for path in outputs]
    return resolved_input not in resolved_outputs and len(set(resolved_outputs)) == len(outputs)


def main(
    argv: Sequence[str] | None = None,
    *,
    verifier_factory: VerifierFactory = _make_verifier,
    source_at: SourceAt = git_source_at,
) -> int:
    parser = argparse.ArgumentParser(
        description="Recover and revalidate paired NatErr Records from Stage-2 rows."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--project-checkout", type=Path, required=True)
    parser.add_argument("--clang-bin", required=True)
    parser.add_argument("--diagtool-bin", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--rejected-out", type=Path, required=True)
    parser.add_argument("--manifest-out", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)

    if not args.project_checkout.is_dir():
        parser.error(f"project checkout does not exist: {args.project_checkout}")
    outputs = (args.out, args.rejected_out, args.manifest_out)
    if not _safe_outputs(args.input, outputs):
        parser.error("input and all output paths must be distinct")
    if verifier_factory is _make_verifier:
        if not Path(args.clang_bin).is_file():
            parser.error(f"patched clang does not exist: {args.clang_bin}")
        if not Path(args.diagtool_bin).is_file():
            parser.error(f"diagtool does not exist: {args.diagtool_bin}")

    for path in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
    verifier = verifier_factory(args.clang_bin, args.diagtool_bin, args.timeout)

    statuses: Counter[str] = Counter()
    input_rows = 0
    accepted = 0
    distinct_diagnostics: set[str] = set()
    sources: set[str] = set()
    with (
        args.input.open(encoding="utf-8") as input_stream,
        args.out.open("w", encoding="utf-8") as output_stream,
        args.rejected_out.open("w", encoding="utf-8") as rejected_stream,
    ):
        for line_number, line in enumerate(input_stream, 1):
            if not line.strip():
                continue
            if args.limit is not None and input_rows >= args.limit:
                break
            input_rows += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                status = "invalid_json"
                statuses[status] += 1
                rejected_stream.write(json.dumps({
                    "line": line_number, "status": status, "detail": str(exc)
                }, sort_keys=True) + "\n")
                continue
            if not isinstance(row, dict):
                status = "invalid_row"
                statuses[status] += 1
                rejected_stream.write(json.dumps({
                    "line": line_number, "status": status,
                    "detail": "row is not a JSON object",
                }, sort_keys=True) + "\n")
                continue

            result = formalize_row(
                row,
                args.project_checkout,
                verifier,
                source_at=source_at,
                expected_project=args.project,
            )
            statuses[result.status] += 1
            if result.record is not None:
                output_stream.write(
                    json.dumps(result.record.to_dict(), sort_keys=True) + "\n"
                )
                accepted += 1
                sources.add(result.record.provenance.source)
                name = result.record.primary_diagnostic.diag_name
                if name:
                    distinct_diagnostics.add(name)
                continue
            rejected_stream.write(json.dumps({
                "instance_id": row.get("instance_id"),
                "project": row.get("project"),
                "source_file": row.get("source_file"),
                "commit_sha": row.get("commit_sha"),
                "fix_sha": row.get("fix_sha"),
                "status": result.status,
                "detail": result.detail,
            }, sort_keys=True) + "\n")

    manifest = {
        "schema_version": 1,
        "input": str(args.input),
        "project": args.project,
        "project_checkout": str(args.project_checkout),
        "compiler": {
            "required_llvm_version": "llvmorg-22.1.8",
            "clang_bin": args.clang_bin,
            "diagtool_bin": args.diagtool_bin,
        },
        "counts": {
            "input_rows": input_rows,
            "accepted": accepted,
            "rejected": input_rows - accepted,
            "statuses": dict(sorted(statuses.items())),
        },
        "accepted": {
            "distinct_diagnostics": len(distinct_diagnostics),
            "sources": len(sources),
        },
        "release_gates": {
            "fix_source_recovered": True,
            "corrected_compiles_cleanly": True,
            "buggy_fails_with_stable_primary_diagnostic": True,
            "test_sources_excluded": True,
        },
        "outputs": {
            "records": str(args.out),
            "rejected": str(args.rejected_out),
        },
    }
    rendered = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    args.manifest_out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
