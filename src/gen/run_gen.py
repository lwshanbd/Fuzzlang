"""CLI: run mechanical mutation generation and write a JSONL of records.

    PYTHONPATH=src python3 src/gen/run_gen.py \
        --clang $PREFIX/bin/clang --diagtool $PREFIX/bin/diagtool \
        --out data/gen/mutate_seed.jsonl

With no --sources, a small built-in set of self-contained correct programs is
used (the simple first run). Otherwise each --sources file is treated as a
correct program (language inferred from extension).

Then measure coverage of the output:
    PYTHONPATH=src python3 src/coverage/run_coverage.py --records <out> --target 3
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Optional, Sequence

from foundation.record import Record
from foundation.verifier.fuzzlang import FuzzlangClangVerifier
from gen.collect import collect_records
from gen.mutate import get, text_mutations
from gen.mutate.base import BaseMutation

# A handful of small, self-contained, *correct* programs to mutate. Variety of
# punctuation (semicolons, commas, brackets, ternary colons) -> variety of
# diagnostics. Kept hermetic (no #include) so -fsyntax-only needs nothing.
SAMPLE_PROGRAMS: list[tuple[str, str, str]] = [
    ("sample:basic", "c",
     "int main(void) {\n    int x = 1;\n    int y = 2;\n    return x + y;\n}\n"),
    ("sample:call", "c",
     "int add(int a, int b) {\n    return a + b;\n}\n"
     "int main(void) {\n    return add(1, 2);\n}\n"),
    ("sample:ternary", "c",
     "int classify(int n) {\n    return n > 0 ? 1 : 0;\n}\n"),
    ("sample:struct", "c",
     "struct P {\n    int x;\n    int y;\n};\n"
     "int main(void) {\n    struct P p;\n    p.x = 1;\n    p.y = 2;\n    return p.x + p.y;\n}\n"),
    ("sample:array", "c",
     "int arr[3] = {1, 2, 3};\n"
     "int main(void) {\n    return arr[0] + arr[1] + arr[2];\n}\n"),
    ("sample:enum", "c",
     "enum Color { RED, GREEN, BLUE };\n"
     "int main(void) {\n    enum Color c = GREEN;\n    return c;\n}\n"),
    ("sample:loop", "c",
     "int main(void) {\n    int a = 1, b = 2;\n    for (int i = 0; i < 3; ++i)\n        a += b;\n    return a;\n}\n"),
    ("sample:switch", "c",
     "int pick(int n) {\n    switch (n) {\n    case 1:\n        return 10;\n    default:\n        return 0;\n    }\n}\n"),
]

_EXT_LANG = {".c": "c", ".cc": "c++", ".cpp": "c++", ".cxx": "c++", ".h": "c++", ".hpp": "c++"}


def _load_sources(paths: Sequence[Path]) -> list[tuple[str, str, str]]:
    out = []
    for p in paths:
        lang = _EXT_LANG.get(p.suffix.lower(), "c++")
        out.append((f"file:{p}", lang, p.read_text(encoding="utf-8", errors="replace")))
    return out


def run_generation(
    programs: Sequence[tuple[str, str, str]],
    verifier: FuzzlangClangVerifier,
    mutations: Optional[Sequence[BaseMutation]] = None,
) -> list[Record]:
    """Run collect over each (source, language, src) program; concatenate records."""
    records: list[Record] = []
    for source, language, src in programs:
        recs = collect_records(src, verifier, source=source,
                               language=language, mutations=mutations)
        records.extend(recs)
        print(f"  [{source}] {language}: {len(recs)} records")
    return records


def main() -> None:
    ap = argparse.ArgumentParser(description="Mechanical mutation generation -> JSONL.")
    ap.add_argument("--clang", default=os.environ.get("FUZZLANG_CLANG_BIN"),
                    help="patched clang (or set FUZZLANG_CLANG_BIN)")
    ap.add_argument("--diagtool", default=os.environ.get("FUZZLANG_DIAGTOOL_BIN"),
                    help="diagtool (or set FUZZLANG_DIAGTOOL_BIN)")
    ap.add_argument("--out", type=Path, required=True, help="output JSONL path")
    ap.add_argument("--sources", type=Path, nargs="*", default=None,
                    help="correct source files to mutate (default: built-in samples)")
    ap.add_argument("--mutations", nargs="*", default=None,
                    help="mutation names to run (default: all text mutations)")
    args = ap.parse_args()

    if not args.clang or not args.diagtool:
        ap.error("need --clang and --diagtool (or FUZZLANG_CLANG_BIN/FUZZLANG_DIAGTOOL_BIN)")

    verifier = FuzzlangClangVerifier(args.clang, args.diagtool, timeout_s=15.0)
    mutations = ([get(n) for n in args.mutations] if args.mutations else text_mutations())
    programs = _load_sources(args.sources) if args.sources else SAMPLE_PROGRAMS

    print(f"[run_gen] {len(programs)} programs, mutations="
          f"{[m.name for m in mutations]}")
    records = run_generation(programs, verifier, mutations)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r.to_dict()) + "\n")
    print(f"[run_gen] wrote {len(records)} records -> {args.out}")


if __name__ == "__main__":
    main()
