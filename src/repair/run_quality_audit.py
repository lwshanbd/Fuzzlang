#!/usr/bin/env python3
"""Audit archived repair generations without re-running a model or compiler."""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Sequence

from foundation.verifier import FuzzlangClangVerifier
from repair.eval.edit_quality import compute_edit_quality
from repair.run_adapter_eval import parse_relative_edit, parse_window_rewrite
from repair.sft_data import make_localized_repair_example


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open() as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at {path}:{line_number}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"non-object JSON at {path}:{line_number}")
            rows.append(value)
    if not rows:
        raise ValueError(f"no rows found in {path}")
    return rows


def _predicted_window(response: str, source_window: str, target_format: str) -> str:
    if target_format == "window-rewrite":
        return parse_window_rewrite(response)
    if target_format == "relative-edit":
        edit = parse_relative_edit(response)
        if edit.end_char > len(source_window):
            raise ValueError("predicted relative edit lies outside source window")
        return edit.apply(source_window)
    raise ValueError(f"unknown target format: {target_format}")


def audit_instances(
    records: Sequence[dict[str, Any]],
    instances: Sequence[dict[str, Any]],
    *,
    target_format: str,
    context_lines: int = 8,
    max_window_chars: int = 8_000,
    max_edit_chars: int = 2_000,
    verifier: Any | None = None,
) -> list[dict[str, Any]]:
    by_id = {str(row.get("record_id")): row for row in records}
    if len(by_id) != len(records):
        raise ValueError("record IDs must be present and unique")
    audited: list[dict[str, Any]] = []
    for instance in instances:
        record_id = str(instance.get("record_id"))
        if record_id not in by_id:
            raise ValueError(f"instance has no matching record: {record_id}")
        record = by_id[record_id]
        example = make_localized_repair_example(
            record,
            context_lines=context_lines,
            max_window_chars=max_window_chars,
            max_edit_chars=max_edit_chars,
        )
        result = {
            "record_id": record_id,
            "diag_name": instance.get("diag_name"),
            "ground_truth_ok": bool(instance.get("ground_truth_ok")),
            "parse_ok": bool(instance.get("parse_ok")),
            "compile_ok": bool(instance.get("compile_ok")),
            "exact_match": bool(instance.get("exact_match")),
        }
        if verifier is not None:
            result.update(
                {
                    "archived_ground_truth_ok": result["ground_truth_ok"],
                    "archived_compile_ok": result["compile_ok"],
                    "archived_exact_match": result["exact_match"],
                }
            )
        try:
            predicted = _predicted_window(
                str(instance.get("response", "")),
                example.source_window,
                target_format,
            )
            gold = example.target.apply(example.source_window)
            result["quality"] = compute_edit_quality(
                example.source_window, predicted, gold
            )
            if verifier is not None:
                provenance = record.get("provenance") or {}
                detail = provenance.get("detail") or {}
                compile_cmd = detail.get("compile_cmd")
                if not isinstance(compile_cmd, list) or not compile_cmd:
                    raise ValueError(f"record {record_id} lacks compile_cmd")
                logical_path = str(
                    detail.get("source_path")
                    or provenance.get("source")
                    or record_id
                )
                predicted_source = (
                    str(record["erroneous_src"])[: example.window_start_char]
                    + predicted
                    + str(record["erroneous_src"])[example.window_end_char :]
                )
                ground_truth = verifier.verify(
                    str(record["corrected_src"]),
                    compile_cmd,
                    logical_path=logical_path,
                )
                verified = verifier.verify(
                    predicted_source,
                    compile_cmd,
                    logical_path=logical_path,
                )
                result["ground_truth_ok"] = bool(ground_truth.ok)
                result["parse_ok"] = True
                result["compile_ok"] = bool(verified.ok)
                result["exact_match"] = (
                    predicted_source == str(record["corrected_src"])
                )
                if not ground_truth.ok:
                    result["ground_truth_stderr_tail"] = (
                        ground_truth.raw_stderr[-2_000:]
                    )
                if verified.diag is not None:
                    result["result_diag_name"] = verified.diag.diag_name
                    result["result_diag_msg"] = verified.diag.diag_msg
        except ValueError as exc:
            result["audit_error"] = str(exc)
        audited.append(result)
    return audited


def summarize_audit(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    eligible = [row for row in rows if row.get("ground_truth_ok")]
    fixes = [row for row in eligible if row.get("compile_ok")]
    nonexact_fixes = [row for row in fixes if not row.get("exact_match")]
    degenerate_fixes = [
        row
        for row in fixes
        if (row.get("quality") or {}).get("degenerate")
    ]
    edit_sizes = [
        int(row["quality"]["predicted_edit_size"])
        for row in fixes
        if (row.get("quality") or {}).get("predicted_edit_size") is not None
    ]
    return {
        "n": len(rows),
        "eligible": len(eligible),
        "stale_ground_truth": len(rows) - len(eligible),
        "eligible_compile_ok": len(fixes),
        "eligible_nonexact_compile_ok": len(nonexact_fixes),
        "degenerate_compile_ok": len(degenerate_fixes),
        "large_deletion_compile_ok": sum(
            bool((row.get("quality") or {}).get("large_deletion"))
            for row in fixes
        ),
        "excessive_edit_compile_ok": sum(
            bool((row.get("quality") or {}).get("excessive_edit"))
            for row in fixes
        ),
        "pure_line_deletion_compile_ok": sum(
            bool((row.get("quality") or {}).get("pure_line_deletion"))
            for row in fixes
        ),
        "empty_repair_compile_ok": sum(
            bool((row.get("quality") or {}).get("empty_repair"))
            for row in fixes
        ),
        "compile_ok_edit_size_min": min(edit_sizes) if edit_sizes else None,
        "compile_ok_edit_size_median": (
            statistics.median(edit_sizes) if edit_sizes else None
        ),
        "compile_ok_edit_size_max": max(edit_sizes) if edit_sizes else None,
        "audit_errors": sum("audit_error" in row for row in rows),
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", required=True)
    parser.add_argument("--instances", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--target-format",
        choices=("relative-edit", "window-rewrite"),
        required=True,
    )
    parser.add_argument("--context-lines", type=int, default=8)
    parser.add_argument("--max-window-chars", type=int, default=8_000)
    parser.add_argument("--max-edit-chars", type=int, default=2_000)
    parser.add_argument("--clang-bin", help="C++ compiler used for revalidation.")
    parser.add_argument("--clang-c-bin", help="C compiler used for revalidation.")
    parser.add_argument("--diagtool-bin", help="diagtool used for revalidation.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if bool(args.clang_bin) != bool(args.diagtool_bin):
        raise ValueError("--clang-bin and --diagtool-bin must be provided together")
    verifier = None
    if args.clang_bin:
        verifier = FuzzlangClangVerifier(
            clang_bin=args.clang_bin,
            clang_c_bin=args.clang_c_bin,
            diagtool_bin=args.diagtool_bin,
            timeout_s=30.0,
        )
    records = _load_jsonl(args.records)
    instances = _load_jsonl(args.instances)
    audited = audit_instances(
        records,
        instances,
        target_format=args.target_format,
        context_lines=args.context_lines,
        max_window_chars=args.max_window_chars,
        max_edit_chars=args.max_edit_chars,
        verifier=verifier,
    )
    summary = summarize_audit(audited)
    summary.update(
        {
            "records": args.records,
            "records_sha256": _sha256(args.records),
            "instances": args.instances,
            "instances_sha256": _sha256(args.instances),
            "target_format": args.target_format,
            "reverified": verifier is not None,
            "clang_bin": args.clang_bin,
            "clang_c_bin": args.clang_c_bin,
            "large_deletion_definition": (
                "prediction removes >=20 non-whitespace chars and retains <50% "
                "of input, while gold does not"
            ),
            "excessive_edit_definition": (
                "predicted_edit_size>20 and >5x gold_edit_size"
            ),
            "pure_line_deletion_definition": (
                "changed input lines>0, changed output lines=0, and "
                "removed_non_whitespace>=5, while gold is not a pure deletion"
            ),
        }
    )
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    with output.with_suffix(".instances.jsonl").open("w") as stream:
        for row in audited:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
