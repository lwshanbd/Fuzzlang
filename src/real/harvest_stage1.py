#!/usr/bin/env python3
"""NatErr Stage 1 CLI: fix-build commit metadata harvest.

For each declared project, clones (or refreshes) a local working copy, walks
git log for fix-build commits on or after the calendar cutoff, and writes a
JSONL manifest. This is the metadata-only stage — no compile attempts here.

Stage 2 (actual compile reproduction on the predecessor SHAs) is project-
specific and not run by this script.

Usage:

    python scripts/harvest_stage1.py \\
        --checkout-root /scratch/natErr/checkouts \\
        --manifest-out  /scratch/natErr/manifest_raw.jsonl

    # Run against a subset of projects:
    python scripts/harvest_stage1.py \\
        --checkout-root /scratch/natErr/checkouts \\
        --manifest-out  /scratch/natErr/llvm_only.jsonl \\
        --only llvm,bitcoin

    # Use a different calendar cutoff:
    python scripts/harvest_stage1.py \\
        --checkout-root /scratch/natErr/checkouts \\
        --manifest-out  /scratch/natErr/manifest_raw.jsonl \\
        --since 2025-07-01

Disk use: each project's checkout is ~200MB-20GB (Chromium/LibreOffice are
the big ones). Budget ~150GB total for all 8. Use --only to pick a subset.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from real.harvest import (
    NATERR_DEFAULT_PROJECTS,
    NATERR_DEFAULT_SINCE,
    NatErrProject,
    harvest_metadata,
    write_manifest,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--checkout-root", required=True, type=Path,
                   help="Directory to clone projects into (one subdir per project).")
    p.add_argument("--manifest-out", required=True, type=Path,
                   help="Output JSONL manifest path.")
    p.add_argument("--since", default=NATERR_DEFAULT_SINCE,
                   help=f"ISO date (YYYY-MM-DD). Default: {NATERR_DEFAULT_SINCE}.")
    p.add_argument("--only", default=None,
                   help="Comma-separated project names to include (default: all 8).")
    p.add_argument("--max-per-project", type=int, default=None,
                   help="Cap candidates per project (smoke/debug).")
    p.add_argument("--author-blocklist-hashes", default=None,
                   help="Comma-separated sha256(email)[:16] hashes to exclude.")
    p.add_argument("--shallow", action="store_true",
                   help="Shallow clone with --since history only (saves disk).")
    p.add_argument("--skip-clone", action="store_true",
                   help="Assume checkouts already exist under --checkout-root.")
    return p.parse_args()


def _project_dir(root: Path, proj: NatErrProject) -> Path:
    return root / proj.name


def _clone_or_update(proj: NatErrProject, dest: Path, *,
                     shallow: bool, since: str) -> None:
    if dest.exists():
        print(f"[stage1] {proj.name}: updating existing checkout", flush=True)
        subprocess.run(["git", "fetch", "--quiet", "origin",
                        proj.default_branch], cwd=dest, check=True)
        subprocess.run(["git", "checkout", "--quiet", proj.default_branch],
                       cwd=dest, check=True)
        subprocess.run(["git", "reset", "--quiet", "--hard",
                        f"origin/{proj.default_branch}"],
                       cwd=dest, check=True)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    args = ["git", "clone", "--quiet"]
    if shallow:
        args.extend(["--shallow-since", since])
    args.extend([proj.git_url, str(dest)])
    args.extend(["--branch", proj.default_branch])
    print(f"[stage1] {proj.name}: cloning from {proj.git_url}", flush=True)
    subprocess.run(args, check=True)


def main() -> int:
    args = _parse_args()

    selected: list[NatErrProject] = list(NATERR_DEFAULT_PROJECTS)
    if args.only:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        selected = [p for p in selected if p.name in wanted]
        if not selected:
            print(f"[stage1] no projects matched --only {args.only!r}", file=sys.stderr)
            return 2

    blocklist = set()
    if args.author_blocklist_hashes:
        blocklist = {x.strip() for x in args.author_blocklist_hashes.split(",") if x.strip()}

    args.checkout_root.mkdir(parents=True, exist_ok=True)

    total_candidates: list = []
    per_project_counts: dict[str, int] = {}
    for proj in selected:
        dest = _project_dir(args.checkout_root, proj)
        try:
            if not args.skip_clone:
                _clone_or_update(proj, dest,
                                 shallow=args.shallow, since=args.since)
            print(f"[stage1] {proj.name}: harvesting commits >= {args.since}", flush=True)
            cands = harvest_metadata(
                proj, dest,
                since_iso_date=args.since,
                author_email_blocklist_hashes=blocklist or None,
                max_candidates=args.max_per_project,
            )
        except subprocess.CalledProcessError as e:
            print(f"[stage1] {proj.name}: git error: {e} — skipping", file=sys.stderr)
            continue
        per_project_counts[proj.name] = len(cands)
        total_candidates.extend(cands)
        print(f"[stage1] {proj.name}: {len(cands)} candidate(s)", flush=True)

    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    write_manifest(total_candidates, args.manifest_out)

    print("[stage1] DONE", flush=True)
    print(f"[stage1]   manifest: {args.manifest_out}", flush=True)
    print(f"[stage1]   total candidates: {len(total_candidates)}", flush=True)
    for name, n in sorted(per_project_counts.items()):
        print(f"[stage1]   {name:20s}  {n:6d}", flush=True)

    # Emit a one-line summary JSON to stdout for easy programmatic pickup.
    print(json.dumps({
        "total": len(total_candidates),
        "per_project": per_project_counts,
        "manifest": str(args.manifest_out),
        "since": args.since,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
