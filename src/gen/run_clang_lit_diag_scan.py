#!/usr/bin/env python3
"""Run real Clang lit tests and collect only patched-Clang diagnostic IDs.

The test sources are coverage evidence only: this writes test outcomes and
compiler stderr logs, never FuzzLang Records or source text.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path


WRAPPER = """#!/usr/bin/env bash
set -uo pipefail
log=$(mktemp "__LOG_DIR__/clang.XXXXXX.log")
out=$(mktemp)
\"__REAL_CLANG__\" \"$@\" >\"$out\" 2>\"$log\"
rc=$?
cat \"$out\"
cat \"$log\" >&2
rm -f \"$out\"
exit $rc
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=Path, required=True)
    parser.add_argument("--llvm-lit", required=True)
    parser.add_argument("--site-config", type=Path, required=True)
    parser.add_argument("--clang-test-root", type=Path, required=True)
    parser.add_argument("--clang", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=32)
    args = parser.parse_args()
    if args.workers <= 0:
        parser.error("workers must be positive")
    args.files = args.files.resolve()
    args.site_config = args.site_config.resolve()
    args.clang_test_root = args.clang_test_root.resolve()
    args.out = args.out.resolve()
    args.work = args.work.resolve()
    files = [Path(p) for p in args.files.read_text().splitlines() if p.strip()]
    args.work.mkdir(parents=True, exist_ok=True)
    logs = args.work / "stderr"
    wrappers = args.work / "wrappers"
    logs.mkdir(exist_ok=True)
    wrappers.mkdir(exist_ok=True)
    for name in ("clang", "clang++"):
        wrapper = wrappers / name
        wrapper.write_text(WRAPPER.replace("__LOG_DIR__", str(logs)).replace(
            "__REAL_CLANG__", args.clang + ("++" if name == "clang++" else "")
        ))
        wrapper.chmod(0o755)

    site = args.work / "lit.site.cfg.py"
    text = args.site_config.read_text()
    site_dir = str(args.site_config.parent)
    text = text.replace("os.path.dirname(__file__)", repr(site_dir))
    text += (
        "\n# Replace only test command substitutions after clang setup.\n"
        f"_fuzzlang_real_clang = r{args.clang!r}\n"
        f"_fuzzlang_wrapper_dir = r{str(wrappers)!r}\n"
        "for _i, (_key, _value) in enumerate(config.substitutions):\n"
        "    if isinstance(_value, str):\n"
        "        _value = _value.replace(_fuzzlang_real_clang + '++', _fuzzlang_wrapper_dir + '/clang++')\n"
        "        _value = _value.replace(_fuzzlang_real_clang, _fuzzlang_wrapper_dir + '/clang')\n"
        "        config.substitutions[_i] = (_key, _value)\n"
    )
    site.write_text(text)

    runner = args.work / "lit-runner.py"
    runner.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(args.clang_test_root.parents[1] / 'llvm' / 'utils' / 'lit')!r})\n"
        "from lit.main import main\n"
        f"main({{'config_map': {{{str(args.clang_test_root / 'lit.cfg.py')!r}: {str(site)!r}}}}})\n"
    )
    command = ["/usr/tce/bin/python3", str(runner), "-j", str(args.workers),
               "-sv", *map(str, files)]
    result = subprocess.run(command, text=True, capture_output=True)
    joined = "\n".join(p.read_text(errors="replace") for p in logs.glob("*.log"))
    ids = sorted({int(x) for x in re.findall(r"^DiagID: (\d+)$", joined, re.M)})
    payload = {
        "schema": "fuzzlang.clang_lit_diagnostic_scan.v1",
        "dataset_policy": "coverage_evidence_only_no_test_source_records",
        "inputs": {"test_files": len(files), "files_list": str(args.files)},
        "compiler": {"clang": args.clang},
        "lit": {"site_config": str(args.site_config), "workers": args.workers,
                "returncode": result.returncode},
        "diagnostic_ids": ids,
        "diagnostic_id_count": len(ids),
        "lit_stdout": result.stdout,
        "lit_stderr": result.stderr,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"[clang-lit-scan] tests={len(files)} ids={len(ids)} rc={result.returncode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
