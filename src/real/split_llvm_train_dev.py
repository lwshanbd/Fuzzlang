#!/usr/bin/env python3
"""P011: Source-provenance X-train / X-dev carve on LLVM (file level).

Carves the LLVM source tree at FILE level into X-train (~80%) and X-dev
(~20%) BEFORE any mutation is generated, so that Fuzzlang-Transformer's
mutations of the same underlying file cannot land in both splits. This is
load-bearing for the v2 Model Selection Protocol: hyperparameter search runs
on X-dev, B2 LoRA SFT trains on X-train, and the eval set (Y mutations) is
project-disjoint from both. Reviewer C's specific objection — "instances
in both splits may be based on the same function and the same fuzzing
rule" — is addressed because the same FILE (and thus the same function
within it) cannot appear in both.

Carve is deterministic via salted SHA-256 of the file's repo-relative path,
so re-running on the same source tree + same salt produces identical splits.

The split is at FILE granularity (not FUNCTION). File ⊃ functions, so
file-level carve is strictly STRONGER than function-level: same function
implies same file, so same function cannot be in both splits.

Output (under --out-dir, default `data/splits/`):
  llvm_x_train_files.txt        repo-relative paths, one per line, sorted
  llvm_x_dev_files.txt          same shape
  llvm_x_split_manifest.json    metadata: counts, salt, llvm HEAD, source dir,
                                per-subsystem breakdown, dedup audit verdict

Usage (login-node OK; small Python, just walks files + sha256):
  PYTHONPATH=. python scripts/split_llvm_train_dev.py \\
      --llvm-src /shared/scratch1/Users/$USER/Fuzzlang/natErr/cks_3/llvm \\
      --out-dir data/splits \\
      --salt fuzzlang-v2-2026-04-23 \\
      --dev-fraction 0.20
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import subprocess
import sys
from pathlib import Path

# Source/header extensions we consider as carve-eligible files. Mutations
# operate on translation units (.c/.cpp) but functions can live in headers,
# so we include both — the carve is over source-provenance, not over TUs.
EXTENSIONS = {".c", ".cc", ".cpp", ".cxx", ".c++", ".m", ".mm",
              ".h", ".hh", ".hpp", ".hxx", ".inc"}

# LLVM project subsystems we care about (top-level dirs under llvm-project/).
# We deliberately INCLUDE every top-level project (clang, mlir, flang, etc.)
# so the carve covers the full source-provenance space the wrapper might
# touch later. We exclude tests/ (intentional regression fixtures), build
# directories, and third-party imported source.
SUBSYSTEM_PREFIXES = (
    "llvm/", "clang/", "clang-tools-extra/", "mlir/", "flang/", "lld/",
    "lldb/", "polly/", "openmp/", "compiler-rt/", "libc/", "libcxx/",
    "libcxxabi/", "libunwind/", "bolt/", "offload/", "pstl/",
)

# Skip these — third-party / generated / test-fixture noise that shouldn't
# count as Fuzzlang-mutable LLVM source.
SKIP_PATH_FRAGMENTS = (
    "/test/",                # explicit per-project test fixtures
    "/tests/",
    "/unittests/",
    "/third-party/",
    "/utils/UpdateTestChecks/",
)


def _walk_source_files(llvm_src: Path) -> list[str]:
    """Return sorted list of repo-relative paths of carve-eligible files."""
    files: list[str] = []
    for sub in SUBSYSTEM_PREFIXES:
        sub_dir = llvm_src / sub
        if not sub_dir.is_dir():
            continue
        for p in sub_dir.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() not in EXTENSIONS:
                continue
            rel = str(p.relative_to(llvm_src))
            if any(frag in f"/{rel}" for frag in SKIP_PATH_FRAGMENTS):
                continue
            files.append(rel)
    files.sort()
    return files


def _bucket(rel_path: str, salt: str, dev_fraction: float) -> str:
    """Deterministic bucket assignment via salted SHA-256.

    Hash the salted path, take the first 8 hex chars (32 bits), normalize
    to [0,1). If < dev_fraction → dev; else → train.
    """
    h = hashlib.sha256(f"{salt}|{rel_path}".encode()).hexdigest()
    bucket_value = int(h[:8], 16) / 0xFFFFFFFF
    return "dev" if bucket_value < dev_fraction else "train"


def _llvm_head(llvm_src: Path) -> str | None:
    try:
        cp = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=llvm_src,
            capture_output=True, text=True, check=False,
        )
        return cp.stdout.strip() or None
    except Exception:
        return None


def _per_subsystem_breakdown(
    train: list[str], dev: list[str],
) -> dict[str, dict[str, int]]:
    """Count files per top-level subsystem in each split."""
    counts: dict[str, dict[str, int]] = collections.defaultdict(
        lambda: {"train": 0, "dev": 0}
    )
    for split, files in (("train", train), ("dev", dev)):
        for f in files:
            sub = f.split("/", 1)[0] + "/"
            counts[sub][split] += 1
    return dict(counts)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--llvm-src", type=Path, required=True,
                   help="LLVM source root (e.g., the Stage-1 cks_3/llvm).")
    p.add_argument("--out-dir", type=Path, default=Path("data/splits"))
    p.add_argument("--salt", default="fuzzlang-v2-2026-04-23",
                   help="Salt for deterministic hashing. Change → reshuffle.")
    p.add_argument("--dev-fraction", type=float, default=0.20)
    args = p.parse_args()

    if not args.llvm_src.is_dir():
        print(f"[carve] missing source dir: {args.llvm_src}", file=sys.stderr)
        return 2

    files = _walk_source_files(args.llvm_src)
    if not files:
        print(f"[carve] no source files found under {args.llvm_src} "
              f"(checked subsystems: {SUBSYSTEM_PREFIXES})", file=sys.stderr)
        return 3

    train: list[str] = []
    dev: list[str] = []
    for rel in files:
        (dev if _bucket(rel, args.salt, args.dev_fraction) == "dev" else train
         ).append(rel)

    # Audit: zero overlap. (Sets are guaranteed disjoint by the bucket
    # function, but we sanity-check explicitly so an audit reader can verify.)
    overlap = set(train) & set(dev)
    overlap_ok = (len(overlap) == 0)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    train_path = args.out_dir / "llvm_x_train_files.txt"
    dev_path = args.out_dir / "llvm_x_dev_files.txt"
    train_path.write_text("\n".join(train) + "\n")
    dev_path.write_text("\n".join(dev) + "\n")

    manifest = {
        "schema_version": 1,
        "task": "P011 source-provenance X-train/X-dev carve",
        "granularity": "file",
        "salt": args.salt,
        "dev_fraction_target": args.dev_fraction,
        "n_total": len(files),
        "n_train": len(train),
        "n_dev": len(dev),
        "dev_fraction_actual": round(len(dev) / max(1, len(files)), 4),
        "llvm_src": str(args.llvm_src),
        "llvm_head": _llvm_head(args.llvm_src),
        "per_subsystem": _per_subsystem_breakdown(train, dev),
        "audit": {
            "overlap_count": len(overlap),
            "overlap_ok": overlap_ok,
            "extensions": sorted(EXTENSIONS),
            "skipped_path_fragments": list(SKIP_PATH_FRAGMENTS),
        },
        "outputs": {
            "train": str(train_path),
            "dev": str(dev_path),
        },
    }
    manifest_path = args.out_dir / "llvm_x_split_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))

    # Brief stdout report.
    print(f"[carve] LLVM HEAD       = {manifest['llvm_head']}", flush=True)
    print(f"[carve] total files     = {len(files):>6}", flush=True)
    print(f"[carve] X-train         = {len(train):>6} "
          f"({len(train)/len(files):.1%})", flush=True)
    print(f"[carve] X-dev           = {len(dev):>6} "
          f"({len(dev)/len(files):.1%})", flush=True)
    print(f"[carve] overlap         = {len(overlap)}", flush=True)
    print(f"[carve] manifest        = {manifest_path}", flush=True)
    print("[carve] per-subsystem (train / dev):")
    for sub in sorted(manifest["per_subsystem"]):
        c = manifest["per_subsystem"][sub]
        total = c["train"] + c["dev"]
        if total == 0:
            continue
        print(f"  {sub:<22s} {c['train']:>6} / {c['dev']:>5} "
              f"(dev {c['dev']/total:.1%})")

    if not overlap_ok:
        print("[carve] FAIL: overlap detected", file=sys.stderr)
        return 4
    print("[carve] G-M2 prerequisite: zero overlap OK", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
