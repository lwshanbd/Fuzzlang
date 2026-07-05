#!/usr/bin/env python3
"""Convert a Gen dataset split into run_sweep's eval format, keeping only the
instances that actually *reproduce* under the patched clang.

A Gen record carries `erroneous_src`, `corrected_src`, `language`, and the
diagnostic(s) seen at generation time — but not the exact compile command
(guided records were mined under many per-config flags). run_sweep needs a
concrete `compile_cmd`, and a repair eval is only meaningful on instances where
the buggy source *fails to compile* and the corrected source *compiles clean*
under that command. So for each record we search a small ladder of per-language
`-std` candidates and keep the first command under which:

    buggy errors  AND  corrected is clean.

We prefer a command whose reproduced diagnostic name matches the recorded one
(so the family breakdown is faithful); otherwise we accept the first command
that reproduces at all. Records that never reproduce (e.g. they needed a
`-cc1`-only flag we don't have) are dropped and counted.

Output rows are exactly what `run_sweep._load_split` consumes:
`{instance_id, buggy_src, compile_cmd, diag_id, diag_name, language,
  corrected_src, diag_match}` where compile_cmd uses the `__CLANG__` / `__SRC__`
placeholders the verifier substitutes.

    PYTHONPATH=src python3 src/repair/prepare_eval.py \
        --split data/gen/splits/eval.jsonl \
        --out   data/gen/splits/eval.repro.jsonl \
        --clang-bin $FUZZLANG_CLANG_BIN --diagtool-bin $FUZZLANG_DIAGTOOL_BIN \
        --workers 48
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from foundation.verifier import FuzzlangClangVerifier

# clang `-x` language token per Gen `language` field.
_XLANG = {
    "c": "c",
    "c++": "c++",
    "objective-c": "objective-c",
    "objective-c++": "objective-c++",
    "hlsl": "hlsl",
}

# `-std` ladder per language, newest first. First command that reproduces wins.
_STDS = {
    "c": ["c2x", "gnu2x", "c17", "c11", "c99"],
    "c++": ["c++2c", "c++2b", "c++20", "c++17", "c++14"],
    "objective-c": ["c2x", "c17", "c11"],
    "objective-c++": ["c++2c", "c++20", "c++17"],
    "hlsl": [None],
}


def _candidate_cmds(language: str) -> list[list[str]]:
    xlang = _XLANG.get(language, "c")
    cmds: list[list[str]] = []
    for std in _STDS.get(language, [None]):
        cmd = ["__CLANG__", "-fsyntax-only", "-x", xlang]
        if std is not None:
            cmd.append(f"-std={std}")
        cmd.append("__SRC__")
        cmds.append(cmd)
    return cmds


def _first_diag(rec: dict) -> dict:
    ds = rec.get("diagnostics") or [{}]
    return ds[0] or {}


def reproduce(rec: dict, verifier: FuzzlangClangVerifier) -> dict | None:
    """Return a run_sweep row if the record reproduces, else None."""
    buggy = rec["erroneous_src"]
    corrected = rec["corrected_src"]
    language = rec.get("language", "c++")
    stored = _first_diag(rec)
    stored_name = stored.get("diag_name")

    fallback: dict | None = None
    for cmd in _candidate_cmds(language):
        vb = verifier.verify(buggy, cmd, logical_path="<buggy>")
        if vb.ok or vb.diag is None:
            continue  # buggy must fail with a real diagnostic
        vc = verifier.verify(corrected, cmd, logical_path="<corrected>")
        if not vc.ok:
            continue  # corrected must be clean under the same command
        row = {
            "instance_id": rec["record_id"],
            "buggy_src": buggy,
            "corrected_src": corrected,
            "compile_cmd": cmd,
            "diag_id": vb.diag.diag_id,
            "diag_name": vb.diag.diag_name,
            "language": language,
            "diag_match": vb.diag.diag_name == stored_name,
        }
        if row["diag_match"]:
            return row  # best case: reproduces the recorded diagnostic exactly
        if fallback is None:
            fallback = row
    return fallback


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--clang-bin", required=True)
    ap.add_argument("--diagtool-bin", required=True)
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--timeout", type=float, default=15.0)
    args = ap.parse_args()

    verifier = FuzzlangClangVerifier(
        clang_bin=args.clang_bin, diagtool_bin=args.diagtool_bin,
        timeout_s=args.timeout,
    )

    records = [json.loads(l) for l in args.split.read_text().splitlines() if l.strip()]
    print(f"[prepare_eval] {len(records)} records from {args.split}", flush=True)

    rows: list[dict] = []
    n_match = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(reproduce, r, verifier): i for i, r in enumerate(records)}
        done = 0
        for f in as_completed(futs):
            done += 1
            row = f.result()
            if row is not None:
                rows.append(row)
                n_match += int(row["diag_match"])
            if done % 200 == 0:
                print(f"  ... {done}/{len(records)} scanned, "
                      f"{len(rows)} reproduce", flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    n = len(records)
    k = len(rows)
    print(f"[prepare_eval] reproduced {k}/{n} = {k/n:.1%} "
          f"({n_match} with exact-diagnostic match, "
          f"{k - n_match} accepted on buggy-fails+corrected-clean only)")
    # language breakdown of the kept set
    from collections import Counter
    langs = Counter(r["language"] for r in rows)
    print(f"[prepare_eval] kept languages: {dict(langs)}")
    print(f"[prepare_eval] -> {args.out}")


if __name__ == "__main__":
    main()
