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
import subprocess

from gen.guided.examples import feature_configs, mine, sweep_configs
from gen.guided.generate import generate_pairs
from gen.guided.prompt import feature_hint
from gen.guided.runline import parse_cc1_configs

_EXTS = (".c", ".cpp", ".cc", ".cxx", ".m", ".mm")


def _guess_language(snippet: str) -> str:
    """Cheap language hint for the LLM prompt, from an example snippet.

    Verification still tries every sweep config, so this only nudges the model
    toward the right language; it does not gate acceptance.
    """
    s = snippet
    if any(t in s for t in ("@interface", "@implementation", "@import", "#import")):
        return "objective-c++" if any(t in s for t in ("::", "template", "class ")) else "objective-c"
    if any(t in s for t in ("template", "namespace ", "::", "std::", "public:", "class ")):
        return "c++"
    return "c"


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
    ap.add_argument("--language", default="c++",
                    help="fallback prompt language (per-diagnostic is auto-guessed)")
    ap.add_argument("--workers", type=int, default=16,
                    help="threads for the multi-config mining sweep")
    ap.add_argument("--gen-workers", type=int, default=12,
                    help="threads for generation (LLM + verify are I/O-bound)")
    ap.add_argument("--no-runline", action="store_true",
                    help="disable mining each file's own %%clang_cc1 RUN-line flags")
    ap.add_argument("--max-cc1-per-file", type=int, default=4,
                    help="cap on RUN-line cc1 configs mined per test file")
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
    ap.add_argument("--catalog-targets", action="store_true",
                    help="target every catalog error diagnostic (even ones with no "
                         "mined example — generated from name + message template)")
    ap.add_argument("--feature-verify", action="store_true",
                    help="also verify pairs under feature/target configs (OpenMP, "
                         "ObjC-ARC, HLSL, OpenCL, modules, SVE/SME...) and hint the "
                         "model toward the feature — unlocks flag-gated diagnostics")
    args = ap.parse_args()

    if not args.clang or not args.diagtool:
        ap.error("need --clang and --diagtool (or FUZZLANG_CLANG_BIN/FUZZLANG_DIAGTOOL_BIN)")

    verifier = FuzzlangClangVerifier(args.clang, args.diagtool, timeout_s=15.0)
    msg_of = {e.name: e.message for e in load_catalog().errors()}

    configs = sweep_configs()
    tests = _read_tests(args.tests, args.limit_tests)

    per_source_cmds = None
    if not args.no_runline:
        resource_dir = subprocess.run(
            [args.clang, "-print-resource-dir"], capture_output=True, text=True
        ).stdout.strip()
        cap = args.max_cc1_per_file

        def per_source_cmds(snippet, _sid):
            return parse_cc1_configs(snippet, resource_dir=resource_dir)[:cap]

    print(f"[run_guided] mining {len(tests)} test files x {len(configs)} sweep configs"
          f"{'' if args.no_runline else ' + per-file RUN-line cc1 flags'} "
          f"({args.workers} workers) ...")
    index, diag_configs = mine(tests, verifier, compile_cmds=configs,
                               per_source_cmds=per_source_cmds,
                               max_per_diag=args.max_per_diag,
                               max_configs_per_diag=3, workers=args.workers)
    print(f"[run_guided] examples for {len(index)} distinct diagnostics")

    # Targets: the mined diagnostics, or (catalog mode) every error diagnostic in
    # the catalog — including the ~2700 we never mined a snippet for, generated
    # from name + message template alone.
    targets = sorted(msg_of) if args.catalog_targets else list(index)
    if args.gaps:
        gap_names = {json.loads(l)["diag_name"]
                     for l in args.gaps.read_text(encoding="utf-8").splitlines() if l.strip()}
        targets = [d for d in targets if d in gap_names]
    if args.limit_diags:
        targets = targets[:args.limit_diags]
    n_with_ex = sum(1 for d in targets if index.get(d))
    print(f"[run_guided] generating for {len(targets)} target diagnostics "
          f"({n_with_ex} with a mined example, {len(targets) - n_with_ex} from catalog only)")

    chat = _build_chat(args.base_url, args.model, args.max_tokens, args.temperature)

    feat_cfgs = []
    if args.feature_verify:
        rdir = subprocess.run([args.clang, "-print-resource-dir"],
                              capture_output=True, text=True).stdout.strip()
        feat_cfgs = feature_configs(rdir)

    def gen_one(diag):
        examples = index.get(diag, [])
        lang = _guess_language(examples[0]) if examples else args.language
        # Verify generated pairs under the language sweep PLUS the configs that
        # actually triggered this diagnostic (RUN-line -fopenmp/-triple) PLUS
        # feature/target configs, so flag-gated diagnostics can be reproduced.
        gen_cmds = configs + diag_configs.get(diag, []) + feat_cfgs
        extra = feature_hint(diag) if args.feature_verify else ""
        return generate_pairs(diag, msg_of.get(diag, ""), examples, chat, verifier,
                              source=f"guided:{diag}", language=lang,
                              compile_cmds=gen_cmds,
                              target_required=args.target_required,
                              samples=args.samples_per_diag, extra=extra)

    # Generation is LLM + verify I/O-bound: run targets concurrently.
    records = []
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max(1, args.gen_workers)) as ex:
        for i, recs in enumerate(ex.map(gen_one, targets), 1):
            records.extend(recs)
            if i % 200 == 0:
                print(f"  ... {i}/{len(targets)} targets, {len(records)} records")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r.to_dict()) + "\n")
    print(f"[run_guided] wrote {len(records)}/{len(targets)} records -> {args.out}")


if __name__ == "__main__":
    main()
