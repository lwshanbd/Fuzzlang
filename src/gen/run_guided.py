"""CLI: guided generation from Clang's regression tests (stage 2).

    PYTHONPATH=src python3 src/gen/run_guided.py \
        --clang $P/bin/clang --diagtool $P/bin/diagtool \
        --tests <llvm>/clang/test \
        --model <model> --base-url http://localhost:8000/v1 \
        --gaps data/gen/gaps.jsonl --out data/gen/guided.jsonl

Mine example snippets per diagnostic from clang/test (run each through the
patched clang), then for each target diagnostic ask the LLM for a fresh
correct/broken pair, verify it, and write Records. Measure the result with
src/coverage/run_coverage.py. Needs an OpenAI-compatible LLM endpoint (e.g. a
local vLLM server) and an OPENAI_API_KEY (use "EMPTY" for an open server).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path

from foundation.diagnostics.catalog import load_catalog
from foundation.verifier.fuzzlang import FuzzlangClangVerifier
from gen.guided.examples import mine_examples
from gen.guided.generate import generate_pairs

_EXTS = (".c", ".cpp", ".cc", ".cxx", ".m", ".mm")


def _read_tests(tests_dir: str, limit: int | None) -> list[tuple[str, str]]:
    paths = sorted(
        p for e in _EXTS for p in glob.glob(os.path.join(tests_dir, "**", f"*{e}"),
                                            recursive=True)
    )
    if limit:
        paths = paths[:limit]
    out = []
    for p in paths:
        try:
            text = Path(p).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        out.append((text, f"clangtest:{os.path.relpath(p, tests_dir)}"))
    return out


def _build_chat(base_url: str, model: str, max_tokens: int, temperature: float):
    from repair.agent.chat_backend import OpenAIChatBackend  # run-layer dependency
    backend = OpenAIChatBackend(model, base_url=base_url,
                                api_key=os.environ.get("OPENAI_API_KEY", "EMPTY"))

    def chat(messages):
        resp = backend.chat(messages=messages, temperature=temperature,
                            max_tokens=max_tokens, n=1)
        return resp[0].text if resp else ""

    return chat


def main() -> None:
    ap = argparse.ArgumentParser(description="Guided generation from clang/test -> JSONL.")
    ap.add_argument("--clang", default=os.environ.get("FUZZLANG_CLANG_BIN"))
    ap.add_argument("--diagtool", default=os.environ.get("FUZZLANG_DIAGTOOL_BIN"))
    ap.add_argument("--tests", required=True, help="clang/test directory to mine")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--base-url", default="http://localhost:8000/v1")
    ap.add_argument("--gaps", type=Path, default=None,
                    help="optional gap-list JSONL; restrict targets to these diagnostics")
    ap.add_argument("--language", default="c++")
    ap.add_argument("--max-per-diag", type=int, default=3,
                    help="cap on mined examples kept per diagnostic")
    ap.add_argument("--samples-per-diag", type=int, default=1,
                    help="LLM attempts per target diagnostic (raises multiplicity)")
    ap.add_argument("--limit-tests", type=int, default=None)
    ap.add_argument("--limit-diags", type=int, default=None)
    ap.add_argument("--max-tokens", type=int, default=1024)
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--target-required", action="store_true",
                    help="keep a pair only if the broken version hits the target diagnostic")
    args = ap.parse_args()

    if not args.clang or not args.diagtool:
        ap.error("need --clang and --diagtool (or FUZZLANG_CLANG_BIN/FUZZLANG_DIAGTOOL_BIN)")

    verifier = FuzzlangClangVerifier(args.clang, args.diagtool, timeout_s=15.0)
    msg_of = {e.name: e.message for e in load_catalog().errors()}

    print(f"[run_guided] mining examples from {args.tests} ...")
    tests = _read_tests(args.tests, args.limit_tests)
    index = mine_examples(tests, verifier, language=args.language,
                          max_per_diag=args.max_per_diag)
    print(f"[run_guided] examples for {len(index)} diagnostics from {len(tests)} test files")

    targets = list(index)
    if args.gaps:
        gap_names = {json.loads(l)["diag_name"]
                     for l in args.gaps.read_text(encoding="utf-8").splitlines() if l.strip()}
        targets = [d for d in targets if d in gap_names]
    if args.limit_diags:
        targets = targets[:args.limit_diags]
    print(f"[run_guided] generating for {len(targets)} target diagnostics")

    chat = _build_chat(args.base_url, args.model, args.max_tokens, args.temperature)
    records = []
    for diag in targets:
        recs = generate_pairs(diag, msg_of.get(diag, ""), index[diag], chat, verifier,
                              source=f"guided:{diag}", language=args.language,
                              target_required=args.target_required,
                              samples=args.samples_per_diag)
        records.extend(recs)
        print(f"  [{diag}] {len(recs)}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r.to_dict()) + "\n")
    print(f"[run_guided] wrote {len(records)}/{len(targets)} records -> {args.out}")


if __name__ == "__main__":
    main()
