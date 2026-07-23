#!/usr/bin/env python3
"""Bind diagnostic targets to bounded windows from real clean source TUs."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from foundation.diagnostics.catalog import load_catalog
from gen.fuzzlang_dsl.code_witness import CodeWitnessRequest
from gen.realcorpus.clean_source_pool import load_clean_sources_jsonl


def _window(source: str, anchor: int) -> tuple[int, int]:
    left = source.rfind("\n", 0, max(0, anchor - 280)) + 1
    newline = source.find("\n", min(len(source), anchor + 520))
    return left, len(source) if newline < 0 else newline + 1


def _anchor_pattern(diag_name: str) -> re.Pattern[str]:
    """Choose a code shape that gives a diagnostic-specific edit room."""
    if "call_" in diag_name:
        return re.compile(r"\b[A-Za-z_]\w*\s*\(")
    if "subscript" in diag_name:
        return re.compile(r"\[")
    if "member_reference" in diag_name:
        return re.compile(r"(?:->|\.)")
    if "invalid_operands" in diag_name:
        return re.compile(r"(?:\+|-|\*|/|==|!=|<|>)")
    if "rparen" in diag_name:
        return re.compile(r"\(")
    if "semi" in diag_name:
        return re.compile(r";")
    return re.compile(r"\breturn\b")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean-sources", type=Path, required=True)
    parser.add_argument("--catalog-dir", required=True)
    parser.add_argument("--diag-name", action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    catalog = load_catalog(args.catalog_dir)
    sources = [source for source in load_clean_sources_jsonl(args.clean_sources)
               if source.language == "c++"]
    requests: list[CodeWitnessRequest] = []
    used: set[str] = set()
    for name in args.diag_name:
        entry = catalog.by_name.get(name)
        if entry is None or not entry.is_error:
            raise ValueError(f"target is not a catalog error: {name}")
        pattern = _anchor_pattern(name)
        selected = next(
            ((item, match) for item in sources if item.source_id not in used
             for match in [pattern.search(item.corrected_src)] if match is not None),
            None,
        )
        if selected is None:
            raise ValueError(f"no real C++ source contains anchor for {name}")
        source, match = selected
        used.add(source.source_id)
        anchor = match.start()
        start, end = _window(source.corrected_src, anchor)
        tablegen = (
            f"def {entry.name} : {entry.severity}<"
            f"{json.dumps(entry.message, ensure_ascii=False)}>"
            + (", DefaultError" if entry.default_error else "") + ";"
        )
        requests.append(CodeWitnessRequest(
            diag_name=entry.name,
            diag_id=None,
            diag_message=entry.message,
            language=source.language,
            tablegen_definition=tablegen,
            source_id=source.source_id,
            source_path=source.source_path,
            project=source.project,
            compile_cmd=source.compile_cmd,
            corrected_src=source.corrected_src,
            window_start=start,
            window_end=end,
        ))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(
        json.dumps(item.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
        for item in requests
    ))
    print(f"[code-witness-requests] requests={len(requests)} uses_llm_api=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
