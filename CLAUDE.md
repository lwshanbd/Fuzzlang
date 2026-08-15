# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

FuzzLang is a **compiler-diagnostic-driven framework** for constructing — and repairing against — a large-scale dataset of Clang (C/C++) compilation errors. Dataset and method are one thing: the compiler diagnostic guides what data we generate, labels every record, and is the verifier signal the repair agent reacts to. Target venue: **CGO, September 2026**. The full research framing is in `docs/FuzzLang-Proposal.md` (read it first).

## Hard rules (load-bearing — do not violate)

- **"DVCR" is permanently abandoned.** The old scaffold called the method "DVCR" (Diagnostic-Verified Code Repair). Never reintroduce that name. The diagnostic-aware repair method is `diag` in code (`repair/methods/diag.py`, `make_diag_runner`); the generic repair search loop is `run_repair_loop`.
- **Errors are introduced into correct code.** Every *core* dataset `Record` (`foundation/record.py`) must carry `corrected_src`; the schema enforces this. Broken-only material (no corrected counterpart) is allowed *only* in `Split.AUXILIARY`, never mixed into the core paired set. Never copy a compiler regression test in as a standalone broken sample.
- **One LLVM version everywhere: `llvmorg-22.1.8`.** The diagnostic catalog (`.td`), the patched clang, and the train/dev splits must all use this exact version, or the coverage denominator and the verifier's name lookup disagree. The `.td` lives in the pinned submodule `external/llvm-project`.
- **`legacy/` is frozen.** It holds the old messy `src/` kept only for reference. Do not develop there; port logic *out* of it into `src/`.

## Layout & conventions

All code lives under `src/`, organized by the proposal's five parts. `src/` is **not** on the import path (it's the "src layout"), so imports are `from foundation.verifier import ...`, never `src.foundation`. There is **no separate `scripts/` or top-level `tests/`** — each direction is self-contained: its library code, its runnable `run_*.py` / `*.sh`, and its `tests/` all live together.

- `foundation/` — shared substrate. `types.py` (`DiagInfo`, `Action`, `AgentState`), `verifier/` (compile → typed `VerifierResult`; `fuzzlang.py` parses the patched clang's `DiagID: N`, `stock.py` falls back to regex), `diagnostics/catalog.py` (parse `.td` → error diagnostics = the coverage **denominator**, **3891** in 22.1.8) + `diagnostics/matcher.py` (message-template → name, the stock-clang fallback), `record.py` (the dataset record schema), `ast_hash.py` (structural dedup), `build_fuzzlang_clang.sh` + `patches/`.
- `coverage/` — **the headline metric.** `tracker.py` counts records against the catalog → covered/total, multiplicity, per-component breakdown, and the **gap list** of uncovered/under-covered diagnostics. `report.py` formats it; `run_coverage.py` is the CLI. Coverage ⟷ Gen is a closed loop: Coverage finds gaps, Gen fills them, Coverage re-measures.
- `gen/` — *(to build)* introduce errors into correct code toward the gap list: mechanical mutation, compiler-evidence-guided mutation, model-assisted mutation. Every candidate is verifier-checked. Port from `legacy/code_modification/` and `legacy/llvm_test_agent/`.
- `real/` — mine real failing commits from OSS git history (`harvest_stage1.py`) and reproduce them (`reproduce_stage2_llvm.py`); `split_llvm_train_dev.py` carves provenance-isolated splits. `data/natErr/` already has Stage-1 manifests for 8 projects (seed only — small, to be expanded).
- `repair/` — the diagnostic-aware repair method + baseline ladder. `agent/` (policy + signal-mode observation), `loop/` (`run_repair_loop`: parallel-branch search with dead-end detection), `methods/` (`b0`–`b3` baselines, `diag.py`, `ablations.py`), `eval/metrics.py` (verified-fix-rate, bootstrap CI), `run_sft.py` (LoRA), `run_sweep.py`. Largely reused as-is from the prior scaffold.

`data/` = dataset seeds/splits. `docs/` = the proposal + ops notes. `external/llvm-project` = the pinned LLVM submodule. On this machine it carries **full history** (558k commits, detached at `ca7933e`, the commit the patched clang was built from) and a full checkout, which NatErr mining depends on; a fresh clone is shallow+sparse and must be deepened before `real/` will work. Root `README.md` is **stale** (old `FUZZ_MODE` wrapper) — ignore it.

## Commands

- There is no `python` on PATH here — use **`python3`**.
- Run all tests: `python3 -m pytest -q` (config in `pyproject.toml`: `pythonpath=["src"]`, `testpaths=["src"]`).
- Run one test file / case: `python3 -m pytest src/foundation/tests/test_diagnostics_catalog.py -q` or append `::test_name`.
- Run a script (needs `src` on the path): `PYTHONPATH=src python3 src/coverage/run_coverage.py --records <jsonl> --target 3 --gap-out <jsonl>`.
- Get the LLVM `.td`: `git submodule update --init external/llvm-project` (pinned to `llvmorg-22.1.8`; already deepened to full history here).
- Optional deps: `pip install -e ".[dev]"` (pytest), `".[llm]"` (torch/transformers/vllm/peft, GPU), `".[harvest]"`.

Development is **test-first** (TDD): write a failing test, watch it fail, then implement. Keep the suite green.

## Status & the gating task

Implemented + tested this cycle: `foundation` (catalog, record, matcher) and `coverage` (tracker, report, CLI). Reused production-grade-and-tested from the prior scaffold: `repair` (verifier/agent/loop/methods/eval), `real` (harvest + LLVM stage-2), the SFT/sweep scripts. `gen/` is not built yet.

**Gating dependency — build the Fuzzlang-patched clang at 22.1.8.** Almost everything downstream (Gen validation, Real reproduction, Repair sweeps, the verifier emitting `DiagID`) needs it. `src/foundation/build_fuzzlang_clang.sh` now defaults to `llvmorg-22.1.8`, but `patches/0001-clang-emit-diag-id-on-stderr.patch` was derived on 19.1.7 and still needs **rebasing across 3 major versions** (expect conflicts) before the build succeeds — then just run `src/foundation/build_fuzzlang_clang.sh`. Building clang is CPU-bound (no GPU needed). Tests that require the patched binary skip until it exists.

Compute note: SFT must be pinned to a single machine (the available clusters exchange data only over the internet); the build/SFT machine choice (GH200 vs MI250X vs Polaris) is still open.

The internal engineering plan and TODO live in `new-docs/` but are **gitignored** (not in this repo); this file is the portable handoff.
