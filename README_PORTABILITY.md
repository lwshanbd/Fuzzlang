# Portability: what runs where

Fuzzlang v2 (DVCR) work is split across three machine roles to keep GPU time on Polaris for GPU-only work and offload CPU/disk-heavy steps.

## Roles

| Role | Hardware | What runs here |
|---|---|---|
| **Polaris @ ALCF** (`diomp`, A100 40GB × 4/node) | Expensive, allocation-limited | (1) Qwen2.5-Coder-7B LoRA SFT for B2/B3. (2) All inference sweeps: B0, B1, B2, DVCR, DVCR−id, DVCR−structure, DVCR−loop × 3 seeds × NatErr. (3) 32B appendix robustness, DTFT sanity. Budget: ~100 node-hours main, ~50 buffer. |
| **CPU-rich machine** (any, e.g. lab workstation or a cheap cloud CPU instance) | Cheap or free, CPU-heavy | (1) Clone + build Fuzzlang-modified LLVM/Clang via `scripts/build_fuzzlang_clang.sh`. (2) Run the NatErr harvest (`scripts/natErr_harvest.sh`, coming next iteration) — clones 8 upstream projects, walks fix-build commits, reproduces compile failures. Disk: ~200 GB peak. CPU: parallel-friendly. (3) Clang verifier farm during the inference sweep (verifier calls are CPU, workers can run off-Polaris and stream results back). |
| **Polaris login node** | Shared, A100 80GB × 1 | Small sanity runs, `pytest tests/`, scaffolding development. Do **not** compile LLVM here (CPU-heavy, shared). Do **not** harvest NatErr here (disk + CPU heavy). |

## The transport mechanism

This repo is the common artifact. Clone it everywhere. Each role installs a different Python extra:

```bash
# Polaris (GPU work)
pip install -e ".[dev,llm]"

# CPU machine (build + harvest)
pip install -e ".[dev,harvest]"

# Polaris login node (scaffolding dev + sanity tests)
pip install -e ".[dev]"
```

All produced artifacts (`llvm-project`, Clang binary, NatErr manifest, JSONL error corpus) ship as file trees that sit outside git, with their paths configured via env vars in the runner scripts.

## Compile discipline (login node)

Per the project-level compile-discipline memory:
- Compile on the login node only for tiny things. Use `-j4` or `-j8`.
- A full `llvm-project` build on the login node would take 10-20 hours at `-j4` and monopolize cores — **don't**. Move to a CPU-rich machine.
- Login node does have an A100 80GB; use it for scaffolding sanity (`pytest tests/`) and short `Qwen2.5-Coder-7B` smoke runs. Go to a compute node for anything > 30 minutes of GPU.

## Sequence

1. **(CPU machine)** `bash scripts/build_fuzzlang_clang.sh`  → produces Fuzzlang-patched `clang` + `diagtool`.
2. **(CPU machine)** run the NatErr harvest (driver script pending) → produces `natErr/manifest.json` + `natErr/errors/*.jsonl`.
3. **(Polaris)** Rsync `natErr/` to `/lus/eagle/projects/diomp/baodi/Fuzzlang/data/` + clang binary to `$HOME/fuzzlang-clang`.
4. **(Polaris)** LoRA-SFT B2/B3 via `scripts/polaris_qsub_sft.sh` (pending) → 8 node-hours.
5. **(Polaris)** Main sweep via `scripts/polaris_qsub_sweep.sh` (pending) → ~92 node-hours across all methods and seeds.
6. **(CPU machine)** Mirror Clang verifier calls off Polaris as a distributed-workers pool if CPU on compute nodes is the bottleneck.

## Current scaffold status (2026-04-23)

What's done:
- `experiments/` — verifier abstraction + stock/Fuzzlang/mock backends, agent scaffold, search loop, terminal/dead-end logic, DVCR method factory.
- `tests/` — 17 unit+smoke tests passing on CPU (P001 + P002 sanity stage).
- `scripts/patches/` — Fuzzlang patches to stock LLVM + diagtool, documented for LLVM 19.1.7.
- `scripts/build_fuzzlang_clang.sh` — one-shot off-Polaris build + verification script.
- `pyproject.toml` — three optional-dependency groups for the three machine roles.

What's pending:
- `experiments/agent/policy_vllm.py` — real LLM policy backed by vLLM.
- `experiments/agent/policy_openai.py` — API-backed policy for quick testing / rebuttal-defense runs.
- `experiments/methods/{b0, b1, b2, b3}.py` — baseline variants (B1 is the most interesting: reuses DVCR's search with SIGNAL_NO_STRUCT).
- `experiments/natErr/harvest.py` — NatErr harvest driver.
- `scripts/polaris_qsub_{sft,sweep}.sh` — PBS job templates.
- `experiments/eval/` — verified_fix_rate + bootstrap CI + per-family breakdown.
