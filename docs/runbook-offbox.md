# Off-Polaris runbook (CPU-rich machine)

> **v2 plan (Round 7 READY, 9.3/10) is now canonical.**
> **Before acting on anything below, read in order:**
> - `refine-logs/FINAL_PROPOSAL.md` — the current canonical plan
> - `refine-logs/OOPSLA_REVIEWS.md` — verbatim reviewer text that drove the v2 revision
> - `refine-logs/EXPERIMENT_PLAN.md` — run-level plan matching v2
> - `refine-logs/EXPERIMENT_TRACKER.md` — flat table of every run to do

Step-by-step for running the CPU-heavy work away from Polaris. Covers:
1. Clone the repo + check out the working branch.
2. Install Python deps.
3. Build Fuzzlang-modified Clang.
4. Run NatErr Stage 1 (fix-build commit harvest). **v2 update: Column B use only; not the headline source anymore.**
5. Stage 2 (compile reproduction). **v2 update: LLVM driver already scaffolded at `scripts/reproduce_stage2_llvm.py`. Per-project drivers for PostgreSQL/FFmpeg/Qt remain TODO.**
6. **v2 NEW: Fuzzlang-Transformer X/Y split pipeline** — generates Column A training set (X-train = LLVM) and Column A eval set (Y = {PostgreSQL, FFmpeg, Qt, Blender}) with AST-hash dedup across X↔Y.
7. **v2 NEW: Source-provenance X-train / X-dev carve on LLVM** — required for the Model Selection Protocol.
8. **v2 NEW: DrRepair (or MACER fallback)** — classical baseline install + containerization.

Polaris work picks up from these artifacts + Stage 2's produced eval split + X/Y mutation splits.

## 0. Prerequisites

You need on the CPU-rich machine:
- `git`, `cmake ≥ 3.20`, `ninja`, `gcc ≥ 11` or `clang ≥ 15`
- Python 3.10+
- Disk: ~200 GB for the 8 project checkouts + LLVM build tree + any reproduction artifacts
- Network: a few tens of GB of git clone bandwidth for Chromium / LibreOffice / Qt / Blender

## 1. Clone the repo

```bash
git clone -b feat/dvcr-scaffolding git@github.com:lwshanbd/Fuzzlang.git
cd Fuzzlang
```

Or if you already have a clone, `git fetch origin && git checkout feat/dvcr-scaffolding && git pull`.

## 2. Install the Python env

Pick ONE of the install profiles declared in `pyproject.toml`:

```bash
# Minimal: unit tests only.
pip install -e ".[dev]"

# Adds requests + gitpython for harvest work.
pip install -e ".[dev,harvest]"

# Adds torch + transformers + vllm + peft (if you also want to run
# inference on this box; skip if this machine has no GPU).
pip install -e ".[dev,llm]"
```

Sanity check:
```bash
pytest tests/ --ignore=tests/test_verifier_fuzzlang_integration.py -q
# expected: 52 passed
```

(The 4 integration tests need the patched Clang, which step 3 builds.)

## 3. Build Fuzzlang-modified Clang

On the Pine cluster, write the LLVM source + build trees to `/shared/scratch1/Users/$USER/`
(per-user 50 TB quota, files older than 14 days auto-cleaned — exactly what
build trees want). The installed clang stays in `$HOME` since it's small (~155 MB)
and persistent.

```bash
# Choose install prefix (anywhere convenient — ~155 MB, keep persistent):
export PREFIX=$HOME/fuzzlang-clang
export JOBS=16            # bump as your CPU count allows; 32 is fine

# Heavy transient trees go on scratch (Pine: /shared/scratch1/Users/$USER):
export SCRATCH=/shared/scratch1/Users/$USER/Fuzzlang
mkdir -p $SCRATCH
export SRC_DIR=$SCRATCH/llvm-project-fuzzlang
export BUILD_DIR=$SCRATCH/llvm-build

# Send the build itself to a SLURM compute node (login node is too small):
srun -p pine --account=app -N 1 -c 32 -t 2:00:00 \
    bash -lc 'module load anaconda3/2024.02 cmake/3.27.9 ninja/x86 && \
              bash scripts/build_fuzzlang_clang.sh'
```

The script:
- Clones `llvm-project` at tag `llvmorg-19.1.7` into `$SRC_DIR` if not already.
- Applies `scripts/patches/0001-clang-emit-diag-id-on-stderr.patch`.
- Configures with Ninja + Release + X86-only + clang-only (no other LLVM projects).
- Builds `clang` + `diagtool`.
- Installs clang + copies diagtool into `$PREFIX/bin/`.
- Smoke-tests that patched clang emits `DiagID: N` and diagtool reverse-looks it up.

Typical wall-clock: 30-90 minutes on a 16-core box. At `-j4` (login-node-safe) expect 3-4 hours.

**Verify**:
```bash
export FUZZLANG_CLANG_BIN=$PREFIX/bin/clang
export FUZZLANG_DIAGTOOL_BIN=$PREFIX/bin/diagtool
pytest tests/test_verifier_fuzzlang_integration.py -v
# expected: 4 passed
```

## 4. Run NatErr Stage 1 harvest

This clones the 8 candidate projects and scans their git log for "fix-build"
commits on or after the calendar cutoff (default: 2025-06-01).

```bash
# Heavy harvest checkouts go on scratch (Pine: /shared/scratch1/Users/$USER):
export SCRATCH=/shared/scratch1/Users/$USER/Fuzzlang
mkdir -p $SCRATCH/natErr

# Smoke first — only 2 projects, cap candidates to 20 each:
PYTHONPATH=. python scripts/harvest_stage1.py \
    --checkout-root $SCRATCH/natErr/checkouts \
    --manifest-out  $SCRATCH/natErr/manifest_raw_smoke.jsonl \
    --only bitcoin,postgresql \
    --max-per-project 20 \
    --shallow
```

Expected output (example):
```
[stage1] bitcoin:   N candidate(s)
[stage1] postgresql:   M candidate(s)
[stage1] DONE
[stage1]   total candidates: N+M
[stage1]   manifest: ./scratch/natErr/manifest_raw_smoke.jsonl
{"total": ..., "per_project": {...}, "manifest": ..., "since": "2025-06-01"}
```

Full 8-project run (disk-heavy, can be overnight) — submit to a compute node:

```bash
export SCRATCH=/shared/scratch1/Users/$USER/Fuzzlang
srun -p pine --account=app -N 1 -c 4 -t 12:00:00 \
    bash -lc "module load anaconda3/2024.02 && \
              source $PWD/.venv/bin/activate && \
              PYTHONPATH=. python scripts/harvest_stage1.py \
                  --checkout-root $SCRATCH/natErr/checkouts \
                  --manifest-out  $SCRATCH/natErr/manifest_raw.jsonl \
                  --shallow"
```

**Faster: 4-node parallel via `scripts/harvest_stage1_parallel.sh`.**
Spreads the 8 projects across 4 SLURM nodes (each gets a whole 64-core node
so they don't contend on a shared NIC). Wall-clock collapses from
~chromium-time-serial to ~chromium-time-alone. Wall-time observed on Pine:
3 of 4 nodes finished in 3-16 min; chromium is the long pole at ~1-2 h.

```bash
bash scripts/harvest_stage1_parallel.sh
# When all done, merge per-node manifests:
cat $SCRATCH/natErr/manifest_node_*.jsonl > data/natErr/manifest_full.jsonl
```

**Reference partial harvest** (7 of 8 projects, smoke + parallel run from
2026-04-23) is committed at `data/natErr/manifest_partial_7projects.jsonl`
(873 candidates: llvm 488, blender 153, libreoffice 94, qt 91, ffmpeg 30,
postgresql 15, bitcoin 2). chromium pending.

Disk estimate per project (shallow clone since 2025-06-01):
- llvm: 3 GB
- chromium: ~20 GB
- ffmpeg: 0.4 GB
- libreoffice: ~5 GB
- postgresql: 0.5 GB
- blender: ~3 GB
- qt (qtbase): ~1.5 GB
- bitcoin: 0.5 GB
- **total: ~35 GB**

The manifest JSONL has one row per candidate commit:
```json
{"project": "bitcoin", "fix_sha": "...", "predecessor_sha": "...",
 "commit_date_iso": "2025-08-15T14:32:10Z", "subject": "fix build: ...",
 "author_email_hash": "abc123..."}
```

### Author blocklist (paper-author filter)

Compute sha256(email)[:16] for each paper author and pass them via
`--author-blocklist-hashes`. Example:

```bash
python -c "import hashlib; print(hashlib.sha256(b'you@example.com').hexdigest()[:16])"
# ab12cd34ef...

python scripts/harvest_stage1.py \
    --checkout-root ./scratch/natErr/checkouts \
    --manifest-out ./scratch/natErr/manifest_raw.jsonl \
    --author-blocklist-hashes ab12cd34ef...,ff99ee88dd...
```

This honors the NatErr purity rule (paper authors must not have contributed
to the eval split).

## 5. Stage 2 (compile reproduction) — partial: postgres prototype works

Stage 2 takes each `predecessor_sha` from the manifest, checks it out, runs
the project's build, and — if compile fails — records the primary diagnostic
using the Fuzzlang-modified Clang. Output: the NatErr eval split
(`data/natErr/main.jsonl`) that `scripts/polaris_qsub_sweep.sh` consumes.

### End-to-end smoke (postgres, 1 instance)

`scripts/reproduce_stage2_smoke.py` codifies a verified end-to-end run for
ONE instance: the postgres `9c9d41af...` predecessor SHA fails to compile
`src/tutorial/funcs.c` (missing `#include "varatt.h"`) with diag_id 5191
(`ext_implicit_function_decl_c99`). Round-trips cleanly through
`FuzzlangClangVerifier`.

```bash
export SCRATCH=/shared/scratch1/Users/$USER/Fuzzlang
srun -p pine --account=app -N 1 -c 16 -t 01:00:00 \
    bash -lc "module load anaconda3/2024.02 && \
              source $PWD/.venv/bin/activate && \
              PYTHONPATH=. python scripts/reproduce_stage2_smoke.py \
                  --postgres-checkout $SCRATCH/natErr/cks_4/postgresql \
                  --out data/natErr/main_smoke.jsonl"
```

The committed `data/natErr/main_smoke.jsonl` is the output from this run.

### Generalizing to a real Stage 2 driver — still TODO

Each project has a different build system (CMake / autotools / meson /
ninja / custom) and a different way to inject `$FUZZLANG_CLANG_BIN` as `CC`.
A per-project driver is needed. The smoke script above is a template for
the postgres path; ffmpeg / llvm-self / qt are good next targets.

**Yield-rate caveat**: manual subject inspection of ~30 ffmpeg/postgres/
bitcoin candidates suggests ~30-50% are not Linux-x86 + compile-time
reproducible (rest are macOS/MSVC/aarch64/mips/build-system-only). Plan for
a fractional yield, not 1:1.

**Sample-size context**: the paper's `refine-logs/FINAL_PROPOSAL.md` targets
N≥3000 main + 500 HPC, with a scope decision tree at <300 / 300-999 /
1000-2999 / ≥3000 cutoffs. The committed 7-project partial harvest gives
873 raw candidates → projected 260-540 usable → "narrow to LLVM
self-hosting depth study" tier per the tree. To reach 1k+ scale, see
`scripts/reproduce_stage2_smoke.py` followups and `refine-logs/`'s S2
(CI failure log) source which is documented but not yet scripted.

Rough protocol (per project):
```bash
for row in $(cat manifest_raw.jsonl); do
    sha=$(echo $row | jq -r .predecessor_sha)
    project=$(echo $row | jq -r .project)
    cd "./scratch/natErr/checkouts/$project"
    git checkout "$sha"
    # Configure project with CC=$FUZZLANG_CLANG_BIN, CXX=$FUZZLANG_CLANG_BIN++
    # Build; if it fails with a SINGLE primary diagnostic, record:
    #   (project, sha, source_file, line, diag_id, diag_name, compile_cmd,
    #    buggy_src_content)
    # as one line in data/natErr/main.jsonl.
done
```

What we want in each output row:
```json
{"instance_id": "<project>-<sha7>-<file-sanitized>",
 "project": "...", "commit_sha": "...", "source_file": "...",
 "compile_cmd": ["__CLANG__", "-c", "__SRC__", "-I", "...", "-std=c++20", ...],
 "buggy_src": "<full source file content at SHA>",
 "diag_id": 1542, "diag_name": "err_expected_semi_declaration",
 "line": 2, "col": 23}
```

The sweep driver (`scripts/run_sweep.py`) already expects this schema.

To write Stage 2: either hand-craft one per-project driver (bitcoin is a good
first target — simple CMake build), or invoke Claude Code on the CPU-rich
machine with this repo checked out and ask for `scripts/run_natErr_stage2_<project>.py`.
Given your ARIS skills are installed, you could use:

```
claude
> /run-experiment NatErr Stage 2 for bitcoin project
```

or simply open an interactive session and ask to generate the driver.

## 6. Ship artifacts back to Polaris

Once Stage 2 is done:

```bash
# From CPU machine:
rsync -avz --progress \
    data/natErr/main.jsonl \
    <polaris-user>@polaris.alcf.anl.gov:/lus/eagle/projects/diomp/baodi/Fuzzlang/data/natErr/main.jsonl

rsync -avz --progress \
    $PREFIX/bin/clang $PREFIX/bin/diagtool \
    <polaris-user>@polaris.alcf.anl.gov:/lus/eagle/projects/diomp/baodi/softwares/fuzzlang-clang/bin/
```

(The second rsync is only needed if you used a different LLVM tag / patch
version than what Polaris already has built; on Polaris the patched clang is
already installed.)

## 7. Kick off the Polaris sweep

Back on Polaris, in the repo:

```bash
source scripts/activate_dvcr.sh
# Smoke:
qsub -v METHOD=b0_zero_shot,SEED=17 scripts/polaris_qsub_sweep.sh

# Full main table (21 jobs):
for METHOD in b0_zero_shot b1_stderr_loop b2_static_sft dvcr dvcr_no_id dvcr_no_structure dvcr_no_loop; do
    for SEED in 17 23 42; do
        qsub -v "METHOD=$METHOD,SEED=$SEED" scripts/polaris_qsub_sweep.sh
    done
done
```

For B2/B3 you first need to train the adapter:
```bash
qsub scripts/polaris_qsub_sft.sh
# wait for completion, then the sweep with ADAPTER set:
qsub -v "METHOD=b2_static_sft,SEED=17,ADAPTER=/lus/eagle/projects/diomp/baodi/softwares/adapters/b2_qwen7b_fuzzlang_lora" scripts/polaris_qsub_sweep.sh
```
