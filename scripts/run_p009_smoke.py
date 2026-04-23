#!/usr/bin/env python3
"""P009 smoke: exercise the X/Y split pipeline end-to-end on a tiny sample.

This does NOT generate real Fuzzlang-Transformer mutations (that requires
running the v1 wrapper as CC during real LLVM/Postgres/FFmpeg/Qt/Blender
builds, which is hours of compute per project). Instead it:

  1. Samples N=50 random source-line spans from the P011-carved X-train
     LLVM file list.
  2. Samples N=50 from the X-dev file list.
  3. Samples N=50 from a Y project (postgres tree, from the Stage-1
     checkout).
  4. Writes each as a synthetic mutation row JSONL.
  5. Runs the AST-hash dedup audit between train/dev/eval.

This proves:
  - The pipeline orchestration end-to-end works (sampling + manifest
    emit + audit + reporting).
  - File-level carve in P011 is enforced — train/dev rows are sampled
    from disjoint file lists, so the audit must report zero
    train ↔ dev collisions.
  - Cross-codebase X ↔ Y dedup logic works.

Real mutation generation (the production pipeline) plugs into the same
JSONL schema (`file_path`, `line`, `mutated_src`/`snippet`) so the audit
script (`scripts/run_p009_dedup_audit.py`) can be re-run unchanged.

Usage:
  PYTHONPATH=. python scripts/run_p009_smoke.py \\
      --llvm-src /shared/scratch1/Users/$USER/Fuzzlang/natErr/cks_3/llvm \\
      --y-src    /shared/scratch1/Users/$USER/Fuzzlang/natErr/cks_4/postgresql \\
      --out-dir  data/splits/p009_smoke/ \\
      --n-train 50 --n-dev 50 --n-eval 50 \\
      --hash-mode text
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from pathlib import Path


def _read_file_list(path: Path) -> list[str]:
    with path.open() as f:
        return [ln.strip() for ln in f if ln.strip()]


def _walk_y_sources(y_src: Path) -> list[str]:
    """Walk a Y project for C/C++ source files, return repo-relative paths."""
    exts = {".c", ".cc", ".cpp", ".cxx", ".h", ".hpp"}
    files: list[str] = []
    for p in y_src.rglob("*"):
        if p.is_file() and p.suffix.lower() in exts:
            try:
                files.append(str(p.relative_to(y_src)))
            except ValueError:
                continue
    return files


def _sample_span(repo_root: Path, rel_path: str,
                 rng: random.Random) -> dict | None:
    """Pick a random source line from rel_path, return a synthetic-mutation
    JSONL row that the dedup audit can hash."""
    full = repo_root / rel_path
    try:
        text = full.read_text(errors="replace")
    except OSError:
        return None
    lines = text.splitlines()
    if len(lines) < 5:
        return None
    line_no = rng.randint(3, len(lines) - 2)  # 1-indexed
    return {
        "file_path": rel_path,
        "line": line_no,
        "mutated_src": text,                  # full source; audit re-extracts window
    }


def _emit(rng: random.Random, repo_root: Path, file_list: list[str],
          n: int, project_label: str, out_path: Path) -> int:
    """Sample N spans, emit JSONL. Returns rows actually written."""
    if not file_list:
        out_path.write_text("")
        return 0
    written = 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        attempts = 0
        while written < n and attempts < n * 5:
            attempts += 1
            rel = rng.choice(file_list)
            row = _sample_span(repo_root, rel, rng)
            if row is None:
                continue
            row["project"] = project_label
            row["mutator_id"] = "smoke_synthetic"
            f.write(json.dumps(row) + "\n")
            written += 1
    return written


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--llvm-src", type=Path, required=True,
                   help="LLVM source root (carve was relative to this).")
    p.add_argument("--y-src", type=Path, required=True,
                   help="A Y project source root (e.g. postgres).")
    p.add_argument("--y-label", default="postgres")
    p.add_argument("--carve-dir", type=Path, default=Path("data/splits"),
                   help="P011 output dir.")
    p.add_argument("--out-dir", type=Path,
                   default=Path("data/splits/p009_smoke"))
    p.add_argument("--n-train", type=int, default=50)
    p.add_argument("--n-dev", type=int, default=50)
    p.add_argument("--n-eval", type=int, default=50)
    p.add_argument("--seed", type=int, default=20260423)
    p.add_argument("--hash-mode", choices=["text", "ast"], default="text")
    args = p.parse_args()

    rng = random.Random(args.seed)

    train_files = _read_file_list(args.carve_dir / "llvm_x_train_files.txt")
    dev_files = _read_file_list(args.carve_dir / "llvm_x_dev_files.txt")
    print(f"[p009-smoke] X-train files = {len(train_files)}", flush=True)
    print(f"[p009-smoke] X-dev files   = {len(dev_files)}", flush=True)

    print(f"[p009-smoke] walking Y src {args.y_src} ...", flush=True)
    y_files = _walk_y_sources(args.y_src)
    print(f"[p009-smoke] Y files       = {len(y_files)}", flush=True)
    if not y_files:
        print("[p009-smoke] FAIL: Y project has no source files", file=sys.stderr)
        return 2

    train_path = args.out_dir / "x_train_smoke.jsonl"
    dev_path = args.out_dir / "x_dev_smoke.jsonl"
    eval_path = args.out_dir / "y_eval_smoke.jsonl"
    n_t = _emit(rng, args.llvm_src, train_files, args.n_train, "llvm",
                train_path)
    n_d = _emit(rng, args.llvm_src, dev_files, args.n_dev, "llvm",
                dev_path)
    n_e = _emit(rng, args.y_src, y_files, args.n_eval, args.y_label,
                eval_path)
    print(f"[p009-smoke] emitted: train={n_t}  dev={n_d}  eval={n_e}",
          flush=True)

    # Run the audit.
    audit_out = args.out_dir / "p009_smoke_audit.json"
    cmd = [
        sys.executable, "scripts/run_p009_dedup_audit.py",
        "--train", str(train_path),
        "--dev", str(dev_path),
        "--eval", str(eval_path),
        "--hash-mode", args.hash_mode,
        "--report-out", str(audit_out),
        "--no-fail-on-collision",                # smoke; report but don't exit-code
    ]
    print(f"[p009-smoke] running audit: {' '.join(cmd)}", flush=True)
    cp = subprocess.run(cmd, env={"PYTHONPATH": ".", **__import__("os").environ},
                        capture_output=False)
    if cp.returncode not in (0, 1):
        print(f"[p009-smoke] audit failed with rc={cp.returncode}",
              file=sys.stderr)
        return 3

    report = json.loads(audit_out.read_text())
    print(f"[p009-smoke] audit verdict: "
          f"{'GREEN' if report['overall_ok'] else 'RED'}", flush=True)
    print(f"[p009-smoke] artifacts:")
    print(f"  {train_path}")
    print(f"  {dev_path}")
    print(f"  {eval_path}")
    print(f"  {audit_out}")
    return 0 if report["overall_ok"] else 4


if __name__ == "__main__":
    sys.exit(main())
