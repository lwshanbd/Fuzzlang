#!/usr/bin/env python3
"""Route generated C++ Injectors to exact target triples from Clang RUN lines.

The corresponding clean-source pools have been independently compiled with the
same target triple.  An Injector is deliberately assigned to at most one group
so aggregate campaign counts are not inflated by duplicate replay.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


GROUPS = (
    ("x86_64_unknown", ("-triple x86_64-unknown-unknown",)),
    ("arm64_linux", ("-triple arm64-linux-gnu",)),
    ("x86_64_linux", ("-triple x86_64-linux-gnu",)),
    # In this build's lit.site.cfg.py, %itanium_abi_triple expands to the
    # configured x86_64-unknown-linux-gnu target triple.
    ("x86_64_unknown_linux", (
        "-triple x86_64-unknown-linux-gnu", "-triple %itanium_abi_triple",
    )),
    ("i386_linux", ("-triple i386-linux",)),
)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--injectors", type=Path, required=True)
    p.add_argument("--mode-profile", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    args = p.parse_args()
    profile = {
        row["diag_name"]: set(row.get("mode_flags", ()))
        for row in map(json.loads, args.mode_profile.open())
    }
    injectors = list(map(json.loads, args.injectors.open()))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    assigned: set[str] = set()
    summary = {}
    for label, flags in GROUPS:
        rows = []
        for injector in injectors:
            injector_id = injector["injector_id"]
            diag_name = injector["target"]["diag_name"]
            if injector_id in assigned or not (profile.get(diag_name, set()) & set(flags)):
                continue
            rows.append(injector)
            assigned.add(injector_id)
        (args.out_dir / f"{label}.jsonl").write_text(
            "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows)
        )
        summary[label] = {
            "injectors": len(rows),
            "target_diagnostics": len({row["target"]["diag_name"] for row in rows}),
            "mode_flags": list(flags),
        }
    (args.out_dir / "manifest.json").write_text(json.dumps({
        "schema": "fuzzlang.cross_target_injector_routes",
        "source": {"injectors": str(args.injectors), "mode_profile": str(args.mode_profile)},
        "groups": summary,
        "unique_injectors": len(assigned),
    }, sort_keys=True, separators=(",", ":")) + "\n")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
