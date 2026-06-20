#!/usr/bin/env python3
"""NatErr Stage 2 *smoke* — end-to-end verified for ONE postgres instance.

This is **not** a general per-project driver. It is the codified version of
the manual end-to-end run that proved the Stage-1 → Stage-2 →
FuzzlangClangVerifier pipeline reproduces a primary diagnostic faithfully.

Pinned target: the postgres commit fixed by `c53775185dc4` (subject:
"Fix compile of src/tutorial/funcs.c"). Predecessor SHA `9c9d41af4db7` is
buggy: missing `#include "varatt.h"` causes
`error: call to undeclared function 'VARSIZE_ANY_EXHDR'`
(diag_id 5191 = `ext_implicit_function_decl_c99`).

Output: one JSONL row in `data/natErr/main.jsonl` matching the schema
that `scripts/run_sweep.py` (and `FuzzlangClangVerifier`) consume:
    {instance_id, project, commit_sha, source_file, compile_cmd,
     buggy_src, diag_id, diag_name, line, col, msg}

Usage (from repo root, on a SLURM compute node, with the patched clang
already at $HOME/fuzzlang-clang):

    srun -p pine --account=app -N 1 -c 16 -t 01:00:00 \\
        bash -lc "module load anaconda3/2024.02 && \\
                  source .venv/bin/activate && \\
                  PYTHONPATH=. python scripts/reproduce_stage2_smoke.py \\
                      --postgres-checkout /shared/scratch1/Users/$USER/Fuzzlang/natErr/cks_4/postgresql \\
                      --out data/natErr/main_smoke.jsonl"

Generalization to a real Stage 2 driver (per-project) is TODO — see
`scripts/RUNBOOK_OFFBOX.md` section 5.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Pinned smoke instance. Do not change without re-validating end-to-end.
PROJECT = "postgresql"
PRED_SHA = "9c9d41af4db7e7f81d0f9abc7dc16402386091b0"
FIX_SHA = "c53775185dc4b17cd951f5fff74c020a2469da27"
SOURCE_FILE = "src/tutorial/funcs.c"
EXPECTED_DIAG_ID = 5191


def _run(cmd: list[str], cwd: Path | None = None, check: bool = True,
         capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=check,
                          capture_output=capture, text=True)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--postgres-checkout", type=Path, required=True,
                   help="Existing postgres clone (from Stage 1).")
    p.add_argument("--workdir", type=Path,
                   default=Path("/tmp/natErr_stage2_postgres"),
                   help="Where to copy + checkout pred SHA.")
    p.add_argument("--clang-bin", type=Path,
                   default=Path.home() / "fuzzlang-clang/bin/clang")
    p.add_argument("--diagtool-bin", type=Path,
                   default=Path.home() / "fuzzlang-clang/bin/diagtool")
    p.add_argument("--out", type=Path,
                   default=Path("data/natErr/main_smoke.jsonl"),
                   help="Output JSONL path (one row appended).")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    if not args.postgres_checkout.is_dir():
        print(f"[stage2-smoke] checkout not found: {args.postgres_checkout}",
              file=sys.stderr)
        return 2
    if not args.clang_bin.is_file():
        print(f"[stage2-smoke] patched clang not found: {args.clang_bin}",
              file=sys.stderr)
        return 2

    # 1. Stage a clean copy at workdir, check out predecessor SHA.
    work = args.workdir
    if work.exists():
        shutil.rmtree(work)
    work.parent.mkdir(parents=True, exist_ok=True)
    print(f"[stage2-smoke] copying {args.postgres_checkout} -> {work}",
          flush=True)
    shutil.copytree(args.postgres_checkout, work, symlinks=True)
    _run(["git", "checkout", "--quiet", PRED_SHA], cwd=work)

    # 2. Configure (minimal: no readline / zlib / icu deps required for funcs.c).
    print("[stage2-smoke] running ./configure (minimal)", flush=True)
    cfg = _run(
        ["./configure", "--without-readline", "--without-zlib", "--without-icu"],
        cwd=work, capture=True, check=False,
    )
    if cfg.returncode != 0:
        print("[stage2-smoke] configure failed:", file=sys.stderr)
        print(cfg.stderr[-2000:], file=sys.stderr)
        return 3

    # 3. Generate header symlinks under src/include (postgres-specific step).
    print("[stage2-smoke] make submake-generated-headers", flush=True)
    _run(["make", "-C", "src", "submake-generated-headers"], cwd=work)

    # 4. Run patched clang on the target source file.
    cflags = ["-Wall", "-Wpointer-arith", "-Wformat-security",
              "-fno-strict-aliasing", "-fwrapv", "-O2", "-w"]
    cppflags = ["-D_GNU_SOURCE", f"-I{work}/src/include"]
    cmd = [str(args.clang_bin), "-fsyntax-only", *cppflags, *cflags,
           f"{work}/{SOURCE_FILE}"]
    print(f"[stage2-smoke] {' '.join(cmd)}", flush=True)
    cc = _run(cmd, capture=True, check=False)
    stderr = cc.stderr
    if cc.returncode == 0:
        print("[stage2-smoke] UNEXPECTED: clang exited 0 — predecessor compiled!",
              file=sys.stderr)
        print(stderr[-2000:], file=sys.stderr)
        return 4

    # 5. Parse the primary (first) error and its DiagID.
    m = re.search(r"^([^\s:]+):(\d+):(\d+): error: (.+?)\n", stderr, flags=re.M)
    if not m:
        print("[stage2-smoke] no `file:line:col: error:` found in stderr",
              file=sys.stderr)
        print(stderr[-2000:], file=sys.stderr)
        return 5
    src_file, line, col, msg = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
    d = re.search(r"^DiagID:\s*(\d+)", stderr[m.end():], flags=re.M)
    if not d:
        print("[stage2-smoke] no `DiagID: N` after primary error", file=sys.stderr)
        return 5
    diag_id = int(d.group(1))
    if diag_id != EXPECTED_DIAG_ID:
        print(f"[stage2-smoke] WARN: got diag_id={diag_id}, expected "
              f"{EXPECTED_DIAG_ID} — toolchain or includes may have shifted",
              file=sys.stderr)

    diag_name = _run([str(args.diagtool_bin), "find-diagnostic-id",
                      str(diag_id)], capture=True).stdout.strip()

    # 6. Buggy source = file content at predecessor SHA.
    buggy_src = _run(["git", "-C", str(work), "show",
                      f"{PRED_SHA}:{SOURCE_FILE}"], capture=True).stdout

    # 7. compile_cmd uses the verifier's __CLANG__ / __SRC__ placeholders.
    #    Includes are absolute on this machine — bundling/portability is a
    #    separate concern (see runbook section 5).
    compile_cmd = ["__CLANG__", "-fsyntax-only",
                   "-D_GNU_SOURCE", f"-I{work}/src/include",
                   *cflags, "__SRC__"]

    inst = {
        "instance_id": f"{PROJECT}-{PRED_SHA[:7]}-funcs_c",
        "project": PROJECT,
        "commit_sha": PRED_SHA,
        "source_file": SOURCE_FILE,
        "compile_cmd": compile_cmd,
        "buggy_src": buggy_src,
        "diag_id": diag_id,
        "diag_name": diag_name,
        "line": line,
        "col": col,
        "msg": msg,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as f:
        f.write(json.dumps(inst) + "\n")
    print(f"[stage2-smoke] wrote {args.out}")
    print(f"[stage2-smoke]   diag_id={diag_id} ({diag_name}) "
          f"@ {SOURCE_FILE}:{line}:{col}")
    print(f"[stage2-smoke]   buggy_src length: {len(buggy_src)} chars")
    return 0


if __name__ == "__main__":
    sys.exit(main())
