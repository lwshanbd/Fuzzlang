# Experiment Tracker (v2, matches FINAL_PROPOSAL.md Round 7)

> Flat run-level table. Each row = one (method × split × seed × config) combination that fills one cell in the paper. Update `Status` as runs launch. MUST = main paper; NICE = appendix / rebuttal-defense.

**Base model (headline)**: Qwen2.5-Coder-7B-Instruct · FP16 · vLLM · matched token envelope `E_tokens = T × K × 256 = 5120` per instance
**Base models (appendix)**: Qwen2.5-Coder-32B-Instruct · Llama-3.3-70B-Instruct · frontier API (GPT-5 or Claude-4.5, optional)
**Eval (Column A, MUTATION)**: Fuzzlang-Transformer mutations on Y = {PostgreSQL, FFmpeg, Qt, Blender}, N = 3000. X-train = LLVM; X-dev carved at source-provenance level before mutation generation; AST-hash dedup across X↔Y.
**Eval (Column B, NATURAL)**: NatErr Stage 2 reproductions from 8 projects, commits ≥ 2025-06-01. N = Stage-2-actual (projected 100–500).
**Seeds (headline rows DVCR + B1)**: `{17, 23, 42}` on both columns.
**Seeds (other main rows)**: `{17, 42}` on both columns — budget trim per plan.

---

## Preparation runs (must-run, single-shot)

| Run ID | Milestone | Purpose | System | Metrics / Output | Priority | Status | Notes |
|---|---|---|---|---|---|---|---|
| P001 | M0 | Verifier wrapper unit tests + JSON-schema edit parser tests | all scaffolding tests | unit pass rate | MUST | DONE | 56 tests passed on Polaris |
| P002 | M0 | Hand-crafted DVCR end-to-end smoke (missing-`;`) | DVCR full | verified_fix_rate 5/5 on synthetic | MUST | DONE | scaffolding OK |
| P003 | M1 | 10-instance dry-run through all 6 main methods | B0, B1, B2, B3, B_classical stub, DVCR | logs + matched-budget envelope verified | MUST | TODO | |
| P004 | M2 | NatErr Stage 1 harvest (8 projects, ≥ 2025-06-01) | — | manifest JSONL | MUST | PARTIAL | 873 raw, 7 projects (chromium pending); already committed to data/natErr/manifest_partial_7projects.jsonl |
| P005 | M2 | Random-sample sanity check of 50 NatErr instances | — | pass/fail for "genuine compile error" | MUST | TODO | catches harvest bugs |
| P006 | M2 | NatErr audit manifest generation | — | per-instance `(project, sha, file, line, diag_id)` | MUST | PARTIAL | manifest_smoke has 1 row |
| P007 | M2 | Paper-author blocklist hashes (NatErr purity rule) | — | sha256(email)[:16] for each co-author | MUST | TODO | |
| P008 | M3 | B2 LoRA SFT training (Qwen2.5-Coder-7B on X-train only) | LoRA rank 16, 1 epoch | adapter weights at `$ADAPTER_OUT` | MUST | TODO | must use X-train only, not full X |
| **P009** | **M2** | **Fuzzlang-Transformer X/Y mutation split pipeline** | Fuzzlang wrapper + split infra | Column A training set (X-train mutations) + Column A eval set (Y mutations) + AST-hash dedup audit | MUST | **TODO (NEW)** | **source-provenance X-dev carve before generation**; Y = {PG, FFmpeg, Qt, Blender} |
| ~~P010~~ | ~~M5~~ | ~~DrRepair / MACER install~~ | — | — | **DROPPED 2026-04-23** | DrRepair has no pretrained ckpt + 2020 stack; MACER GitHub 404; BIFI same problem. B_classical removed from main table per FINAL_PROPOSAL §Evaluation rationale. |
| **P011** | **M2** | **X-dev source-provenance carve on LLVM** | pre-mutation split | X-train.json / X-dev.json with file/function/commit manifests; dedup audit | MUST | **TODO (NEW)** | **load-bearing for the Model Selection Protocol** |
| P012 | M4 | NatErr Stage 2 LLVM driver (`scripts/run_natErr_stage2_llvm.py`) | FuzzlangClangVerifier + compile_commands.json | Column B LLVM subset + reproduction_rate statistic | MUST | **REDO IN PROGRESS 2026-04-23** | First attempt: 0/488 reproduced (G-M4 fail); root cause was clang-only build (mlir/lld/lldb/etc TUs missing) + Stage-1 included bazel/td-only fixes. Redo: (a) `scripts/filter_manifest_source_changes.py` keeps only fix_sha that touched ≥1 C/C++ file → 242/488 kept (49.6%); (b) full subprojects build (clang;lld;lldb;mlir;flang;polly;clang-tools-extra) at `$SCRATCH/p012-full-build`. |
| **P012b** | **M4** | **Stage-1 source-touch filter** | post-process | filtered manifest at `data/natErr/manifest_llvm_source_only.jsonl` | MUST | **DONE 2026-04-23** | 242/488 LLVM kept; report: `data/natErr/manifest_llvm_source_only.filter_report.json` |
| P013 | M4b | NatErr Stage 2 postgres driver (beyond smoke) | per-project | Column B postgres subset | MUST | TODO | smoke already works |
| P014 | M4b | NatErr Stage 2 ffmpeg driver | per-project | Column B ffmpeg subset | MUST | TODO (NEW) | |
| P015 | M4b | NatErr Stage 2 qt driver | per-project | Column B qt subset | MUST | TODO (NEW) | |
| P016 | M4b | NatErr Stage 2 blender driver (optional) | per-project | Column B blender subset | NICE | TODO (NEW) | |

---

## Block B1 — Main two-column table (MUST-RUN) · 5 methods × 3 seeds × 2 columns = 30 headline runs (was 6×3×2=36 before B_classical was dropped 2026-04-23)

### Column A (Mutation on Y, N = 3000)

| Run ID | Milestone | System | Seed | Metrics | Status | Notes |
|---|---|---|---|---|---|---|
| RA001 | M6 | B0 zero-shot | 17 | verified_fix_rate@T=5 | TODO | doubles as Column A contamination floor |
| RA002 | M6 | B0 zero-shot | 23 | — | TODO | |
| RA003 | M6 | B0 zero-shot | 42 | — | TODO | |
| RA004 | M6 | B1 stderr-loop | 17 | primary + token_eff + avg_turns | TODO | **headline baseline** |
| RA005 | M6 | B1 stderr-loop | 23 | — | TODO | |
| RA006 | M6 | B1 stderr-loop | 42 | — | TODO | |
| RA007 | M6 | B2 static SFT | 17 | primary | TODO | uses P008 adapter |
| RA008 | M6 | B2 static SFT | 42 | — | TODO | 2 seeds per budget-trim rule |
| RA009 | M6 | B3 SFT+stderr-loop | 17 | primary | TODO | B2 adapter + B1 loop |
| RA010 | M6 | B3 SFT+stderr-loop | 42 | — | TODO | |
| ~~RA011~~ | ~~M6~~ | ~~B_classical DrRepair~~ | — | — | **DROPPED** | see P010 |
| ~~RA012~~ | ~~M6~~ | ~~B_classical DrRepair~~ | — | — | **DROPPED** | |
| **RA013** | **M6** | **DVCR (ours)** | **17** | all primary + secondary | **TODO** | **headline cell** |
| RA014 | M6 | DVCR (ours) | 23 | — | TODO | |
| RA015 | M6 | DVCR (ours) | 42 | — | TODO | |

**Gate C1-A**: `mean(RA013-RA015).verified_fix_rate − mean(RA004-RA006).verified_fix_rate ≥ 5 pp` with non-overlapping 95% bootstrap CI. If fail, **pause** and diagnose before running ablations.

### Column B (Natural NatErr, N = Stage-2-actual)

| Run ID | Milestone | System | Seed | Metrics | Status | Notes |
|---|---|---|---|---|---|---|
| RB001 | M8 | B0 zero-shot | 17 | primary | TODO | |
| RB002 | M8 | B0 zero-shot | 23 | — | TODO | |
| RB003 | M8 | B0 zero-shot | 42 | — | TODO | |
| RB004 | M8 | B1 stderr-loop | 17 | primary | TODO | **headline baseline** |
| RB005 | M8 | B1 stderr-loop | 23 | — | TODO | |
| RB006 | M8 | B1 stderr-loop | 42 | — | TODO | |
| RB007 | M8 | B2 static SFT | 17 | primary | TODO | |
| RB008 | M8 | B2 static SFT | 42 | — | TODO | 2 seeds |
| RB009 | M8 | B3 SFT+stderr-loop | 17 | primary | TODO | |
| RB010 | M8 | B3 SFT+stderr-loop | 42 | — | TODO | |
| ~~RB011~~ | ~~M8~~ | ~~B_classical DrRepair~~ | — | — | **DROPPED** | see P010 |
| ~~RB012~~ | ~~M8~~ | ~~B_classical DrRepair~~ | — | — | **DROPPED** | |
| **RB013** | **M8** | **DVCR (ours)** | **17** | all primary + secondary | **TODO** | **headline cell** |
| RB014 | M8 | DVCR (ours) | 23 | — | TODO | |
| RB015 | M8 | DVCR (ours) | 42 | — | TODO | |

**Gate C1-B**: `mean(RB013-RB015).verified_fix_rate > mean(RB004-RB006).verified_fix_rate` directionally (same sign). Loose CI OK given smaller N. If gate fails on Column B but passes on Column A, report honestly as "Column A passes; Column B underpowered / mixed results at N=XX".

---

## Block B2 — Causal ablations (MUST-RUN, on Column A primarily) · 3 × 3 = 9 runs

| Run ID | Milestone | System / Observation | Split | Seed | Metrics | Status | Notes |
|---|---|---|---|---|---|---|---|
| RA016 | M7 | **DVCR − id** (structured, no ID) | Column A | 17 | primary | TODO | **middle cell** |
| RA017 | M7 | DVCR − id | Column A | 23 | — | TODO | |
| RA018 | M7 | DVCR − id | Column A | 42 | — | TODO | |
| RA019 | M7 | **DVCR − structure** (raw stderr only) | Column A | 17 | primary | TODO | should approximate B1 |
| RA020 | M7 | DVCR − structure | Column A | 23 | — | TODO | |
| RA021 | M7 | DVCR − structure | Column A | 42 | — | TODO | |
| RA022 | M7 | **DVCR − loop** (T=1, K=4) | Column A | 17 | primary | TODO | |
| RA023 | M7 | DVCR − loop | Column A | 23 | — | TODO | |
| RA024 | M7 | DVCR − loop | Column A | 42 | — | TODO | |

**Gate C2**: `mean(RA013-RA015) − mean(RA016-RA018) ≥ 3 pp` with non-overlapping CI. If fail, honest-report path — rewrite thesis to "structured-feedback verifier" variant.

---

## Block B3 — Rigor audit (post-hoc, no new runs)

| Item | Source | Output | Priority | Status | Notes |
|---|---|---|---|---|---|
| B3a | RA001-RA003, RB001-RB003 | Contamination floor on both columns | MUST | TODO | reported in Table 1 footnote |
| B3b | P005, P009, P011 | Split-purity audit (X/Y disjoint; AST-dedup; temporal; no paper-authors) | MUST | TODO | audit manifest released |
| B3c | all RA* + RB* | Seed variance 95% CI per reported number | MUST | TODO | target < 3 pp width |
| B3d | all RA* + RB* | Macro vs micro avg | MUST | TODO | flags head-class inflation |
| B3e | model-selection log | Protocol audit trail (which decisions on X-dev, when frozen) | MUST | TODO | **critical** — load-bearing for paper defense |

---

## Block B4 — Limitations / safety subset (MUST-RUN, appendix)

| Run ID | Milestone | System | Split | Seed | Metrics | Priority | Status | Notes |
|---|---|---|---|---|---|---|---|---|
| RL001 | M9 | DVCR | A subset with tests | 17 | `(compile_ok ∧ tests_pass)` | MUST | TODO | |
| RL002 | M9 | DVCR | B subset with tests | 17 | same | MUST | TODO | |
| RL003 | M9 | B1 | A subset with tests | 17 | same | MUST | TODO | comparator |
| RL004 | M9 | B1 | B subset with tests | 17 | same | MUST | TODO | |
| RL005 | M9 | 3-5 case studies of DVCR "success but wrong" | — | — | narrative | MUST | TODO | writing task |

---

## Block B5 — Failure analysis (post-hoc)

| Item | Source | Output | Priority | Status |
|---|---|---|---|---|
| B5a | RA013-RA015 logs | Per-diagnostic-family breakdown on Column A | MUST | TODO |
| B5b | RA013-RA015 FAIL cases | Dead-end (diag_id, span_hash) distribution | MUST | TODO |
| B5c | RA013-RA015 logs | Trivial-deletion-reject rate | MUST | TODO |
| B5d | Column A + B | 3-5 qualitative trajectory narratives | MUST | TODO |

---

## Block C1 — Scale calibration (NICE-TO-HAVE, appendix)

| Run ID | Milestone | System (base model) | Split | N | Metrics | Priority | Status | Notes |
|---|---|---|---|---|---|---|---|---|
| RC001 | M10 | DVCR (Qwen 32B) | A subset | 1000 | primary | NICE | TODO | |
| RC002 | M10 | B1 (Qwen 32B) | A subset | 1000 | primary | NICE | TODO | |
| RC003 | M10 | DVCR (Llama 3.3 70B) | A subset | 500 | primary | NICE | TODO | 20 node-hours alone |
| RC004 | M10 | B1 (Llama 3.3 70B) | A subset | 500 | primary | NICE | TODO | |
| RC005 | M10 | DVCR (frontier API: GPT-5 or Claude-4.5) | A subset | 300 | primary | NICE | TODO | no Polaris cost |
| RC006 | M10 | B1 (frontier API) | A subset | 300 | primary | NICE | TODO | |

---

## Block C2 — Domain + cross-compiler (NICE-TO-HAVE, appendix)

| Run ID | Milestone | System | Split | Seed | Priority | Status | Notes |
|---|---|---|---|---|---|---|---|
| RC007 | M10 | B0 | HPC OpenMP+OpenACC subset of NatErr | 17 | NICE | TODO | |
| RC008 | M10 | B1 | HPC subset | 17 | NICE | TODO | |
| RC009 | M10 | B2 | HPC subset | 17 | NICE | TODO | |
| RC010 | M10 | DVCR | HPC subset | 17 | NICE | TODO | |
| RC011 | M10 | DVCR + B1 | GCC cross-compiler transfer (N=1000) | 17 | NICE | TODO | needs diag-ID crosswalk |

---

## Block C3 — Mechanism depth (NICE-TO-HAVE, appendix)

| Run ID | Milestone | System | Split | Seed | Priority | Status | Notes |
|---|---|---|---|---|---|---|---|
| RC012 | M10 | DVCR T ∈ {1,2,3,5,10} sweep | A subset (1000) | 17 | NICE | TODO | budget sensitivity |
| RC013 | M10 | DVCR trajectory trim {1,2,full} | A subset (1000) | 17 | NICE | TODO | |
| RC014 | M10 | DVCR + notes-inclusion variant | A subset (1000) | 17 | NICE | TODO | |
| RC015 | M10 | DTFT sanity (LoRA on DVCR trajectories) | A | 17 | NICE | TODO | |
| RC016 | M10 | Synthetic stress test (X-train mutations, in-distribution) | X-train | 17 | NICE | TODO | |

---

## Status legend

- `TODO` — not started
- `RUNNING` — in progress
- `DONE` — data collected, not yet in paper
- `PAPER` — results locked in a table/figure
- `BLOCKED` — gate failure or dependency unresolved
- `CANCELLED` — decided against

---

## Gate summary (for run-experiment decision routing)

| Gate | Condition | If pass | If fail |
|---|---|---|---|
| **G-M0** | P001, P002 green | → M1 | fix scaffolding bugs |
| **G-M2** | AST-hash dedup audit passes on X-train / X-dev and X / Y | → M3 (SFT can start) | **halt**, debug split infra |
| **G-M4** | NatErr Stage 2 LLVM reproduction rate measured | → M4b for other projects OR demote Column B if rate < 10% | — |
| ~~G-M5~~ | ~~DrRepair smoke~~ | — | **DROPPED** 2026-04-23 — see P010 |
| **G-C1-A** (headline) | DVCR − B1 ≥ 5 pp non-overlapping CI on Column A | → M7 ablations | **halt**, diagnose DVCR scaffolding |
| **G-C2** (causal) | DVCR − DVCR-id ≥ 3 pp non-overlapping CI on Column A | → paper claim 2 stands | honest-report path: thesis weakens to "structured verifier" |
| **G-C1-B** | DVCR > B1 directionally on Column B | → paper claim 1-B stands | Column B → appendix; paper on Column A alone |

---

## Reality checks before each launch

- [ ] P001 verifier unit tests passing
- [ ] P002 hand-crafted DVCR trajectory succeeds
- [ ] P003 dry-run of 6 methods on 10 synthetic instances produces valid logs
- [ ] P009 Fuzzlang-Transformer X/Y split produced; **AST-hash dedup audit green** (no shared hashes X-train ↔ Y-eval)
- [ ] P011 X-dev carve produced at source-provenance level; X-train ↔ X-dev share NO source function/file
- [ ] P008 B2 LoRA SFT validation loss monotonic; trained on X-train only (not full X)
- [ ] P010 DrRepair (or MACER fallback) smoke passes
- [ ] P012 NatErr Stage 2 LLVM reproduction_rate measured and ≥ 10% (or Column B demoted to appendix with explicit note)
- [ ] Matched-budget envelope `E_tokens = 5120` enforced in harness for all loop and single-shot methods
- [ ] 95% bootstrap CI computation wired before M6 launches
- [ ] **Model Selection Protocol frozen**: hyperparameter config + prompt text + schema snapshot hash-committed to repo BEFORE any Column A / Column B eval run is launched

---

## Handoff

`/run-experiment` (or the Pine-side equivalent wrapper) can consume this tracker directly. Run IDs are stable. Gate failures trigger pauses, not workarounds.
