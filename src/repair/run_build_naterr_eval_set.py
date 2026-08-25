#!/usr/bin/env python3
"""Turn reproduced NatErr rows into an evaluation set of real developer errors.

Stage 2 leaves rows carrying the erroneous source, the compile command, and the
diagnostic it reproduced. The repair prompt also needs the developer's own fix,
because the source window is centred on the edit between the two -- so this
recovers it with ``git show <fix_sha>:<path>``.

Note what is *not* required: that the recovered fix compiles. Only 3 of 269 do,
because the surrounding tree has moved on since the commit, and demanding it
throws away 266 real errors to protect a scoring convention. The errors
themselves reproduce under the pinned compiler, which is what makes them usable;
:mod:`repair.naterr_eval` scores them on whether the shown diagnostic is gone
rather than on a clean build.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Sequence

from gen.realcorpus.corpus import is_test_path


def _source_at(checkout: Path, revision: str, repo_path: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "show", f"{revision}:{repo_path}"],
            cwd=checkout, capture_output=True, text=True,
            errors="replace", timeout=60.0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", required=True, help="Stage-2 reproduced JSONL.")
    parser.add_argument("--checkout", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--manifest-out")
    args = parser.parse_args(argv)

    rows = [
        json.loads(line)
        for line in Path(args.rows).read_text().splitlines() if line.strip()
    ]
    checkout = Path(args.checkout)
    status: Counter[str] = Counter()
    records = []
    for row in rows:
        source_path = str(row.get("source_file") or "")
        if is_test_path(source_path):
            status["test_source"] += 1
            continue
        corrected = _source_at(checkout, str(row.get("fix_sha")), source_path)
        if not corrected:
            status["fix_source_unavailable"] += 1
            continue
        erroneous = row.get("buggy_src")
        if not isinstance(erroneous, str) or not erroneous:
            status["missing_erroneous_src"] += 1
            continue
        if corrected == erroneous:
            status["fix_does_not_change_source"] += 1
            continue
        try:
            diag_id = int(row["diag_id"])
        except (KeyError, TypeError, ValueError):
            status["missing_diag_id"] += 1
            continue
        status["accepted"] += 1
        records.append({
            "record_id": row.get("instance_id"),
            "erroneous_src": erroneous,
            "corrected_src": corrected,
            "language": "c" if source_path.lower().endswith((".c", ".m")) else "c++",
            "split": "eval",
            "diagnostics": [{
                "diag_id": diag_id,
                "diag_name": row.get("diag_name"),
                "diag_msg": row.get("msg"),
                "file": source_path,
                "line": int(row.get("line") or 0),
                "col": int(row.get("col") or 0),
                "start_byte": 0, "end_byte": 0, "span_snippet": "",
            }],
            "provenance": {
                "origin": "real",
                "source": f"{row.get('project')}:{source_path}",
                "detail": {
                    "strategy": "naterr_commit_history",
                    "project": row.get("project"),
                    "source_path": source_path,
                    "predecessor_sha": row.get("commit_sha"),
                    "fix_sha": row.get("fix_sha"),
                    "compile_cmd": row.get("compile_cmd"),
                    "target_diag": row.get("diag_name"),
                    "target_diag_id": diag_id,
                },
            },
        })

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in records)
    )
    manifest = {
        "schema": "fuzzlang.naterr_eval_set.v1",
        "rows_in": len(rows),
        "records": len(records),
        "status": dict(sorted(status.items())),
        "inputs": {"rows": args.rows, "checkout": args.checkout},
        "note": (
            "Errors are real; the reference fix is the developer's commit and "
            "is not required to compile in the current tree."
        ),
    }
    if args.manifest_out:
        Path(args.manifest_out).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
