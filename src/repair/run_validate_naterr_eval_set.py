#!/usr/bin/env python3
"""Keep only the NatErr instances that are real developer errors.

Compiling a file from 2023 against a tree from 2026 invents errors nobody made:
a header deleted since, a member that has moved. Those reproduce exactly like a
real error, so the erroneous side alone cannot tell them apart.

The discriminator is the developer's own commit. Applying their fix and
recompiling: if the same diagnostic still fires, they were not fixing it, and
scoring a model on it would score our reconstruction rather than a repair.
Instances that fail that test are dropped, with the reason recorded.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Sequence

from foundation.verifier import FuzzlangClangVerifier
from repair.naterr_eval import is_real_developer_error


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--report-out")
    parser.add_argument("--clang-bin", required=True)
    parser.add_argument("--clang-c-bin")
    parser.add_argument("--diagtool-bin", required=True)
    parser.add_argument("--jobs", type=int, default=16)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args(argv)

    verifier = FuzzlangClangVerifier(
        clang_bin=args.clang_bin, diagtool_bin=args.diagtool_bin,
        clang_c_bin=args.clang_c_bin, timeout_s=args.timeout,
    )
    records = [
        json.loads(line)
        for line in Path(args.records).read_text().splitlines() if line.strip()
    ]

    def check(record: dict) -> tuple[dict, str]:
        detail = record["provenance"]["detail"]
        try:
            result = verifier.verify(
                str(record["corrected_src"]), detail["compile_cmd"],
                logical_path=detail["source_path"],
            )
        except Exception as exc:  # a broken command is not a real error either
            return record, f"verify_failed:{type(exc).__name__}"
        if result.raw_stderr == "__TIMEOUT__":
            return record, "timeout"
        if is_real_developer_error(result, target_diag_id=detail["target_diag_id"]):
            return record, "kept_clean" if result.ok else "kept_other_errors_remain"
        return record, "dropped_fix_does_not_address_diagnostic"

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        outcomes = list(pool.map(check, records))

    status = Counter(reason for _, reason in outcomes)
    kept = [record for record, reason in outcomes if reason.startswith("kept")]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in kept))

    by_diag = Counter(
        r["provenance"]["detail"]["target_diag"] for r in kept
    )
    dropped_by_diag = Counter(
        record["provenance"]["detail"]["target_diag"]
        for record, reason in outcomes if not reason.startswith("kept")
    )
    report = {
        "schema": "fuzzlang.naterr_eval_validation.v1",
        "records_in": len(records),
        "records_kept": len(kept),
        "status": dict(sorted(status.items())),
        "kept_by_diagnostic": dict(by_diag.most_common(15)),
        "dropped_by_diagnostic": dict(dropped_by_diag.most_common(15)),
        "criterion": (
            "kept when recompiling the developer's own fix no longer reports "
            "the target diagnostic; dropped otherwise, because a fix that does "
            "not address the diagnostic means the diagnostic is an artifact of "
            "compiling historical source against the current tree."
        ),
    }
    if args.report_out:
        Path(args.report_out).write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n"
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
