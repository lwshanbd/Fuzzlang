#!/usr/bin/env python3
"""Filter a NatErr Stage-1 manifest, keeping only candidates whose `fix_sha`
commit touched at least one C/C++ source file.

This addresses the P012 G-M4 root cause: 287/488 (58.8%) LLVM candidates'
fix-build commits modified ONLY non-source files (bazel BUILD, cmake,
TableGen .td, JSON, README, scripts). These can never be reproduced by
Stage 2 — clang has nothing to compile. Stage 1's keyword filter
("fix.*build") correctly catches them as fix-build commits, but Stage 2
can only verify source-level errors. Drop them at the boundary.

Usage:
  PYTHONPATH=. python scripts/filter_manifest_source_changes.py \\
      --in  data/natErr/manifest_full_8projects.jsonl \\
      --out data/natErr/manifest_full_8projects_source_only.jsonl \\
      --project llvm \\
      --checkout-root /shared/scratch1/Users/$USER/Fuzzlang/natErr/cks_3 \\
      --jobs 16

The --project flag scopes the filter to one project (since each project's
fix_sha lives in its own checkout). To process all projects, run multiple
times and concat OR omit --project and pass --checkout-map.

Source extensions kept:
  .c .cc .cpp .cxx .c++ .h .hh .hpp .hxx .inc .m .mm
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import subprocess
import sys
from pathlib import Path

SOURCE_EXTS = {".c", ".cc", ".cpp", ".cxx", ".c++",
               ".h", ".hh", ".hpp", ".hxx", ".inc",
               ".m", ".mm"}


def _files_touched(repo: Path, sha: str) -> list[str]:
    cp = subprocess.run(
        ["git", "show", "--name-only", "--pretty=format:", sha],
        cwd=repo, capture_output=True, text=True, timeout=30,
    )
    if cp.returncode != 0:
        return []
    return [ln.strip() for ln in cp.stdout.splitlines() if ln.strip()]


def _row_keeps(args: tuple) -> tuple[dict, bool, list[str]]:
    row, repo_str = args
    files = _files_touched(Path(repo_str), row["fix_sha"])
    src_files = [f for f in files
                 if Path(f).suffix.lower() in SOURCE_EXTS]
    return row, len(src_files) > 0, src_files


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="inp", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--project", required=True,
                   help="Only process rows of this project. Use 'ALL' "
                        "with --checkout-map to process all projects.")
    p.add_argument("--checkout-root", type=Path, default=None,
                   help="Directory containing <project>/ checkouts.")
    p.add_argument("--jobs", type=int, default=8)
    p.add_argument("--report-out", type=Path, default=None)
    args = p.parse_args()
    args.report_out = args.report_out or args.out.with_suffix(".filter_report.json")

    if args.project == "ALL":
        print("[filter] ALL not yet supported (TODO: per-project routing)",
              file=sys.stderr)
        return 2
    if not args.checkout_root:
        print("[filter] --checkout-root required when --project != ALL",
              file=sys.stderr)
        return 2
    repo = args.checkout_root / args.project
    if not (repo / ".git").is_dir():
        print(f"[filter] missing .git at {repo}", file=sys.stderr)
        return 2

    rows = []
    other = []
    with args.inp.open() as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            r = json.loads(ln)
            (rows if r.get("project") == args.project else other).append(r)
    print(f"[filter] project={args.project}: input rows = {len(rows)}", flush=True)
    print(f"[filter] (other-project rows passed through unchanged: {len(other)})",
          flush=True)

    tasks = [(r, str(repo)) for r in rows]
    keep_rows: list[dict] = []
    drop_rows: list[dict] = []
    drop_examples: list[dict] = []  # capture a few for the report
    with mp.get_context("fork").Pool(processes=args.jobs) as pool:
        for i, (row, keeps, src_files) in enumerate(
                pool.imap_unordered(_row_keeps, tasks)):
            if keeps:
                row["fix_touched_sources"] = src_files
                keep_rows.append(row)
            else:
                drop_rows.append(row)
                if len(drop_examples) < 10:
                    drop_examples.append({
                        "fix_sha": row["fix_sha"],
                        "subject": row.get("subject", "")[:120],
                    })
            if (i + 1) % 50 == 0:
                print(f"[filter]   {i+1}/{len(tasks)}  "
                      f"keep={len(keep_rows)} drop={len(drop_rows)}",
                      flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as f:
        for r in keep_rows + other:                # keep other-project rows too
            f.write(json.dumps(r) + "\n")

    report = {
        "task": "P012 root-cause filter (source-touch on fix commit)",
        "input": str(args.inp),
        "output": str(args.out),
        "project_filtered": args.project,
        "input_rows_for_project": len(rows),
        "kept_rows_for_project": len(keep_rows),
        "dropped_rows_for_project": len(drop_rows),
        "drop_rate_for_project":
            round(len(drop_rows) / max(1, len(rows)), 4),
        "passthrough_other_project_rows": len(other),
        "source_extensions": sorted(SOURCE_EXTS),
        "drop_examples": drop_examples,
    }
    args.report_out.write_text(json.dumps(report, indent=2, sort_keys=True))
    print(f"[filter] kept    {len(keep_rows)}  ({len(keep_rows)/max(1,len(rows)):.1%})",
          flush=True)
    print(f"[filter] dropped {len(drop_rows)}  ({len(drop_rows)/max(1,len(rows)):.1%})",
          flush=True)
    print(f"[filter] manifest -> {args.out}", flush=True)
    print(f"[filter] report   -> {args.report_out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
