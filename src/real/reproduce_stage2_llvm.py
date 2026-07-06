#!/usr/bin/env python3
"""NatErr Stage 2 driver for LLVM self-hosting candidates.

Why LLVM first:
  - Largest Stage-1 bucket (488 candidates, 56% of the 7-project harvest).
  - Well-understood build (cmake + ninja, our own build script already works).
  - Self-referential story ("compile the compiler") is the most natural
    evaluation domain for a compiler-diagnostic-based repair method.
  - If LLVM alone yields >= 300 usable instances, the paper can stand on an
    LLVM-only depth study without needing the other 6 projects.

Strategy (fast, no per-candidate rebuilds):
  1. Do ONE baseline build of LLVM at a recent `origin/main`, with
     `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON`. Produces `compile_commands.json`.
     This captures the exact compile command (with include paths, flags,
     generated headers, etc.) for every translation unit.
  2. For each candidate in the Stage 1 manifest:
     a. git-diff the FIX commit to find which *.c/*.cpp/*.h files it touched.
     b. For each modified source file, pull the PREDECESSOR version via
        `git show <pred_sha>:<file>`.
     c. Look up the compile command from compile_commands.json. Strip any
        `-o <output>` and force `-fsyntax-only` so we never write .o.
     d. Replace `__CLANG__` / `__SRC__` placeholders, feed buggy source via
        stdin (`-` arg) OR write to a temp file (simpler), and run patched
        clang.
     e. If compile fails with a clean primary diagnostic (first `error:` +
        `DiagID:`), record the instance. Otherwise: no-repro, multi-error,
        or file-not-in-compile-db → count and skip.
  3. Write JSONL to `data/natErr/llvm_main.jsonl` + a summary JSON with
     reproduction rate statistics.

This does NOT rebuild LLVM per candidate. Total runtime for 488 candidates:
  - baseline build: ~30-60 min one-time on 32-core box
  - per candidate: ~5-15 sec (git show + one clang invocation)
  - TOTAL: ~2 hours wall on 16 parallel workers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from foundation.compile_db import build_clang_argv as _shared_build_clang_argv
from foundation.compile_db import load_compile_db as _shared_load_compile_db
from foundation.compile_db import split_command as _shared_split_command


# ----- Tunables -----

DEFAULT_LLVM_GIT = "https://github.com/llvm/llvm-project.git"
DEFAULT_BRANCH = "main"
SOURCE_EXTENSIONS = (".c", ".cc", ".cpp", ".cxx", ".c++", ".m", ".mm")

_ERROR_LINE = re.compile(
    r"^(?P<file>[^:\n]+):(?P<line>\d+):(?P<col>\d+):\s*(?:fatal\s+)?error:\s*(?P<msg>.*)$",
    re.MULTILINE,
)
_DIAG_ID_LINE = re.compile(r"^DiagID:\s*(\d+)\s*$", re.MULTILINE)


# ----- Data classes -----

@dataclass
class Candidate:
    project: str
    fix_sha: str
    predecessor_sha: str
    commit_date_iso: str
    subject: str
    author_email_hash: str

    @classmethod
    def from_row(cls, row: dict) -> "Candidate":
        return cls(**{k: row[k] for k in cls.__annotations__})


@dataclass
class StageResult:
    """One attempted (candidate, file) pair's outcome."""

    kind: str            # "reproduced" | "no_error" | "multi_error" | "file_not_in_db"
                         # | "no_modified_sources" | "git_error" | "clang_timeout" | "clang_crash"
    candidate: Candidate
    modified_file: Optional[str] = None
    diag_id: Optional[int] = None
    diag_name: Optional[str] = None
    line: Optional[int] = None
    col: Optional[int] = None
    msg: Optional[str] = None
    detail: Optional[str] = None


# ----- Helpers -----

def _run(cmd: list[str], *, cwd: Optional[Path] = None,
         timeout: float = 60.0, check: bool = False,
         capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=cwd, timeout=timeout, check=check,
        capture_output=capture, text=True,
    )


def _ensure_llvm_checkout(llvm_src: Path, branch: str) -> None:
    if llvm_src.exists():
        print(f"[stage2-llvm] using existing checkout {llvm_src}", flush=True)
        return
    print(f"[stage2-llvm] cloning llvm-project to {llvm_src}", flush=True)
    llvm_src.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--branch", branch, DEFAULT_LLVM_GIT, str(llvm_src)],
        check=True,
    )


def _build_baseline(llvm_src: Path, build_dir: Path, jobs: int) -> Path:
    """Configure + build LLVM once to produce compile_commands.json."""
    build_dir.mkdir(parents=True, exist_ok=True)
    ccdb = build_dir / "compile_commands.json"
    if ccdb.exists():
        print(f"[stage2-llvm] reusing existing {ccdb}", flush=True)
        return ccdb
    print(f"[stage2-llvm] configuring LLVM (jobs={jobs})", flush=True)
    cmake_cmd = [
        "cmake", "-G", "Ninja", str(llvm_src / "llvm"),
        "-DCMAKE_BUILD_TYPE=Release",
        "-DLLVM_ENABLE_PROJECTS=clang",
        "-DLLVM_TARGETS_TO_BUILD=X86",
        "-DLLVM_ENABLE_ASSERTIONS=OFF",
        "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
        f"-DLLVM_PARALLEL_COMPILE_JOBS={jobs}",
        "-DLLVM_PARALLEL_LINK_JOBS=2",
    ]
    subprocess.run(cmake_cmd, cwd=build_dir, check=True)
    print(f"[stage2-llvm] building clang to realize generated headers", flush=True)
    # Building clang populates all generated `.inc` files that subsequent
    # compiles reference. Without this, many TUs fail to find those headers.
    subprocess.run(["ninja", f"-j{jobs}", "clang"], cwd=build_dir, check=True)
    if not ccdb.exists():
        raise RuntimeError(f"compile_commands.json not produced at {ccdb}")
    return ccdb


def _load_compile_db(ccdb_path: Path) -> dict[str, dict]:
    """Index compile_commands.json by the (absolute source file path) key.

    Each entry has `directory`, `command` or `arguments`, `file`.
    """
    index = _shared_load_compile_db(ccdb_path)
    print(f"[stage2-llvm] compile_commands.json: {len(index)} TUs", flush=True)
    return index


def _relpath(abs_path: str, llvm_src: Path) -> Optional[str]:
    try:
        p = Path(abs_path).resolve().relative_to(llvm_src.resolve())
        return str(p)
    except ValueError:
        return None


def _files_modified_in_commit(llvm_src: Path, sha: str) -> list[str]:
    """Return list of repo-relative paths modified in commit `sha` filtered to
    source extensions we care about."""
    r = _run(["git", "show", "--name-only", "--pretty=format:", sha],
             cwd=llvm_src, timeout=30.0)
    if r.returncode != 0:
        return []
    names: list[str] = []
    for ln in r.stdout.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if ln.lower().endswith(SOURCE_EXTENSIONS):
            names.append(ln)
    return names


def _buggy_source_at_sha(llvm_src: Path, sha: str, repo_path: str) -> Optional[str]:
    r = _run(["git", "show", f"{sha}:{repo_path}"],
             cwd=llvm_src, timeout=30.0)
    if r.returncode != 0:
        return None
    return r.stdout


def _split_command(entry: dict) -> list[str]:
    """compile_commands.json entries use `command` (shell string) OR
    `arguments` (list). Return the argv list."""
    return _shared_split_command(entry)


def _build_clang_argv(entry: dict, clang_bin: str, src_tmpfile: str) -> list[str]:
    """Transform the recorded compile command into one we can run on buggy src:
    - Replace compiler with patched clang.
    - Drop `-o <out>` (we only want -fsyntax-only).
    - Drop any trailing source path and append our tmp source.
    - Force `-fsyntax-only` to avoid .o writes.
    """
    return _shared_build_clang_argv(entry, clang_bin, src_tmpfile)


def _reverse_lookup_diagname(diagtool_bin: str, diag_id: int,
                             cache: dict[int, Optional[str]]) -> Optional[str]:
    if diag_id in cache:
        return cache[diag_id]
    try:
        r = _run([diagtool_bin, "find-diagnostic-id", str(diag_id)], timeout=5.0)
        if r.returncode == 0:
            name = r.stdout.strip().split("\n", 1)[0] or None
        else:
            name = None
    except subprocess.TimeoutExpired:
        name = None
    cache[diag_id] = name
    return name


def _attempt_reproduce(
    candidate: Candidate, entry: dict, modified_rel: str,
    buggy_src: str, clang_bin: str, diagtool_bin: str,
    diag_name_cache: dict[int, Optional[str]], timeout: float = 30.0,
) -> StageResult:
    """Run patched clang on buggy source using the recorded compile command."""
    # Preserve file extension so clang dispatches the right frontend.
    ext = Path(modified_rel).suffix or ".c"
    with tempfile.NamedTemporaryFile("w", suffix=ext, delete=False) as tf:
        tf.write(buggy_src)
        tmp_path = tf.name
    try:
        argv = _build_clang_argv(entry, clang_bin, tmp_path)
        try:
            cp = _run(argv, cwd=entry.get("directory"), timeout=timeout)
        except subprocess.TimeoutExpired:
            return StageResult(kind="clang_timeout", candidate=candidate,
                               modified_file=modified_rel,
                               detail=f"timeout after {timeout}s")
        if cp.returncode == 0:
            return StageResult(kind="no_error", candidate=candidate,
                               modified_file=modified_rel,
                               detail="clang exited 0 — predecessor compiled")
        # Parse primary error.
        stderr = cp.stderr
        m = _ERROR_LINE.search(stderr)
        if not m:
            # Possibly the compiler crashed or emitted errors in an unusual format.
            tail = stderr[-400:]
            return StageResult(kind="clang_crash", candidate=candidate,
                               modified_file=modified_rel,
                               detail=f"no `file:line:col: error:` in stderr. "
                                      f"rc={cp.returncode}. tail={tail!r}")
        d = _DIAG_ID_LINE.search(stderr[m.end():])
        if not d:
            return StageResult(kind="clang_crash", candidate=candidate,
                               modified_file=modified_rel,
                               detail="no `DiagID: N` after primary error")
        diag_id = int(d.group(1))
        diag_name = _reverse_lookup_diagname(
            diagtool_bin, diag_id, diag_name_cache,
        )

        # Count cascade errors. We RELAX the previous "n_errors > 5 ⇒ reject"
        # rule because legitimate compile failures (missing #include,
        # missing type declaration) routinely cascade into 10-30 follow-up
        # errors — Reviewer-C-style "primary diagnostic" is exactly the
        # FIRST one, which we already captured. Tag cascade size for
        # downstream filtering instead.
        n_errors = len(list(_ERROR_LINE.finditer(stderr)))

        return StageResult(
            kind="reproduced", candidate=candidate, modified_file=modified_rel,
            diag_id=diag_id, diag_name=diag_name,
            line=int(m.group("line")), col=int(m.group("col")),
            msg=m.group("msg").strip(),
            detail=f"n_cascade_errors={n_errors}",
        )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _instance_id(project: str, pred_sha: str, modified_rel: str) -> str:
    sha7 = pred_sha[:7]
    stem = Path(modified_rel).stem
    # Ensure uniqueness if the same stem appears multiple times.
    h = hashlib.sha256(modified_rel.encode()).hexdigest()[:6]
    return f"{project}-{sha7}-{stem}-{h}"


def _process_candidate(
    cand: Candidate, llvm_src: Path, compile_db: dict[str, dict],
    clang_bin: str, diagtool_bin: str, diag_name_cache: dict[int, Optional[str]],
    timeout: float,
) -> list[StageResult]:
    """Return 0+ StageResult records for this candidate."""
    # Find files modified in the FIX commit (forward-sha).
    modified = _files_modified_in_commit(llvm_src, cand.fix_sha)
    if not modified:
        return [StageResult(kind="no_modified_sources", candidate=cand,
                            detail="fix commit touched no C/C++ sources")]
    results: list[StageResult] = []
    for rel in modified:
        abs_path = os.path.realpath(str(llvm_src / rel))
        entry = compile_db.get(abs_path)
        if entry is None:
            results.append(StageResult(kind="file_not_in_db",
                                       candidate=cand, modified_file=rel,
                                       detail=f"{rel} not in compile_commands.json"))
            continue
        buggy_src = _buggy_source_at_sha(llvm_src, cand.predecessor_sha, rel)
        if buggy_src is None:
            results.append(StageResult(kind="git_error",
                                       candidate=cand, modified_file=rel,
                                       detail=f"git show failed for "
                                              f"{cand.predecessor_sha}:{rel}"))
            continue
        results.append(_attempt_reproduce(
            cand, entry, rel, buggy_src, clang_bin, diagtool_bin,
            diag_name_cache, timeout=timeout,
        ))
    return results


def _worker(task: tuple) -> list[dict]:
    """multiprocessing worker. Returns dicts so IPC is pickle-cheap."""
    cand_row, llvm_src, compile_db_path, clang_bin, diagtool_bin, timeout = task
    cand = Candidate.from_row(cand_row)
    # Each worker loads the compile_db once; but workers persist across tasks
    # only with a pool. For simplicity, load per-task and cache on module.
    global _CDB_CACHE
    try:
        _CDB_CACHE
    except NameError:
        _CDB_CACHE = _load_compile_db(Path(compile_db_path))
    results = _process_candidate(
        cand, Path(llvm_src), _CDB_CACHE, clang_bin, diagtool_bin,
        diag_name_cache={}, timeout=timeout,
    )
    return [asdict(r) for r in results]


_CDB_CACHE: dict[str, dict]  # type: ignore[misc]


# ----- Main -----

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", type=Path, required=True,
                   help="Stage 1 manifest JSONL (from harvest_stage1.py).")
    p.add_argument("--llvm-src", type=Path, required=True,
                   help="LLVM checkout (preferably the Stage 1 one; this "
                        "script does NOT clone if missing — clone ahead).")
    p.add_argument("--build-dir", type=Path, required=True,
                   help="Where to run the baseline build + find compile_commands.json.")
    p.add_argument("--clang-bin", type=Path, required=True,
                   help="Fuzzlang-patched clang.")
    p.add_argument("--diagtool-bin", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True,
                   help="Output JSONL: one row per reproduced instance.")
    p.add_argument("--summary-out", type=Path, default=None,
                   help="Optional JSON summary path. Default: <out>.summary.json")
    p.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 4) // 2),
                   help="Parallel workers for per-candidate processing.")
    p.add_argument("--build-jobs", type=int, default=None,
                   help="Parallel jobs for the one-time baseline build.")
    p.add_argument("--timeout", type=float, default=30.0,
                   help="Per-invocation clang timeout (seconds).")
    p.add_argument("--limit", type=int, default=None,
                   help="Cap number of candidates (smoke/debug).")
    p.add_argument("--skip-build", action="store_true",
                   help="Assume compile_commands.json already exists at --build-dir.")
    return p.parse_args()


def _tally(rows: list[dict]) -> dict:
    from collections import Counter
    kinds = Counter(r["kind"] for r in rows)
    n_cand_attempted = len({(r["candidate"]["fix_sha"]) for r in rows})
    reproduced = kinds.get("reproduced", 0)
    return {
        "n_result_rows": len(rows),
        "n_candidates_attempted": n_cand_attempted,
        "n_reproduced_files": reproduced,
        "by_kind": dict(kinds),
        # reproduction_rate: fraction of candidates that had AT LEAST one
        # reproduced file. Honest rate; not #reproduced-rows / #rows.
        "n_candidates_with_any_repro":
            len({r["candidate"]["fix_sha"] for r in rows if r["kind"] == "reproduced"}),
        "reproduction_rate_by_candidate":
            (len({r["candidate"]["fix_sha"] for r in rows if r["kind"] == "reproduced"})
             / max(1, n_cand_attempted)),
    }


def main() -> int:
    args = _parse_args()
    args.summary_out = args.summary_out or args.out.with_suffix(".summary.json")

    if not args.clang_bin.is_file():
        print(f"[stage2-llvm] missing clang: {args.clang_bin}", file=sys.stderr)
        return 2
    if not args.llvm_src.is_dir():
        print(f"[stage2-llvm] missing llvm checkout: {args.llvm_src}", file=sys.stderr)
        return 2

    # Load manifest (filter to LLVM rows).
    candidates: list[Candidate] = []
    with args.manifest.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("project") != "llvm":
                continue
            candidates.append(Candidate.from_row(row))
    if args.limit is not None:
        candidates = candidates[: args.limit]
    print(f"[stage2-llvm] manifest: {len(candidates)} LLVM candidates", flush=True)

    # Baseline build.
    build_jobs = args.build_jobs or max(1, (os.cpu_count() or 4))
    if not args.skip_build:
        _build_baseline(args.llvm_src, args.build_dir, build_jobs)
    ccdb_path = args.build_dir / "compile_commands.json"
    if not ccdb_path.exists():
        print(f"[stage2-llvm] compile_commands.json not found at {ccdb_path}",
              file=sys.stderr)
        return 3

    # Distribute candidates across worker processes.
    args.out.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    tasks = [(asdict(c), str(args.llvm_src), str(ccdb_path),
              str(args.clang_bin), str(args.diagtool_bin), args.timeout)
             for c in candidates]

    all_rows: list[dict] = []
    # Always load compile_db in main process — needed for the emit phase
    # below (build the placeholdered compile_cmd from the canonical entry).
    # Workers ALSO load their own copy when forked, but the main process's
    # copy is what the emit loop uses.
    global _CDB_CACHE
    _CDB_CACHE = _load_compile_db(ccdb_path)
    if args.jobs <= 1:
        for i, task in enumerate(tasks):
            all_rows.extend(_worker(task))
            if (i + 1) % 20 == 0:
                t = _tally(all_rows)
                print(f"[stage2-llvm] {i+1}/{len(tasks)}  "
                      f"repro={t['n_candidates_with_any_repro']} "
                      f"rate={t['reproduction_rate_by_candidate']:.2f}",
                      flush=True)
    else:
        with mp.get_context("fork").Pool(processes=args.jobs) as pool:
            for i, rows in enumerate(pool.imap_unordered(_worker, tasks)):
                all_rows.extend(rows)
                if (i + 1) % 20 == 0:
                    t = _tally(all_rows)
                    print(f"[stage2-llvm] {i+1}/{len(tasks)}  "
                          f"repro={t['n_candidates_with_any_repro']} "
                          f"rate={t['reproduction_rate_by_candidate']:.2f}",
                          flush=True)

    # Emit reproduced rows in the schema that run_sweep.py consumes.
    n_emitted = 0
    with args.out.open("w") as out:
        for row in all_rows:
            if row["kind"] != "reproduced":
                continue
            cand = row["candidate"]
            rel = row["modified_file"]
            # Re-lookup entry to build a portable compile_cmd with placeholders.
            abs_path = os.path.realpath(str(args.llvm_src / rel))
            entry = _CDB_CACHE[abs_path]
            argv = _build_clang_argv(entry, "__CLANG__", "__SRC__")
            inst = {
                "instance_id": _instance_id(cand["project"],
                                            cand["predecessor_sha"], rel),
                "project": cand["project"],
                "commit_sha": cand["predecessor_sha"],
                "fix_sha": cand["fix_sha"],
                "source_file": rel,
                "compile_cmd": argv,
                "buggy_src": _buggy_source_at_sha(
                    args.llvm_src, cand["predecessor_sha"], rel) or "",
                "diag_id": row["diag_id"],
                "diag_name": row["diag_name"],
                "line": row["line"],
                "col": row["col"],
                "msg": row["msg"],
            }
            out.write(json.dumps(inst) + "\n")
            n_emitted += 1

    summary = _tally(all_rows)
    summary.update({
        "elapsed_sec": round(time.time() - t0, 2),
        "manifest": str(args.manifest),
        "llvm_src": str(args.llvm_src),
        "n_emitted_rows": n_emitted,
    })
    args.summary_out.write_text(json.dumps(summary, indent=2, sort_keys=True))

    print(f"[stage2-llvm] DONE", flush=True)
    print(f"[stage2-llvm]   wrote {n_emitted} reproduced rows -> {args.out}",
          flush=True)
    print(f"[stage2-llvm]   summary -> {args.summary_out}", flush=True)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
