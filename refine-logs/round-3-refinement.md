# Round 3 Refinement

## Problem Anchor (verbatim, unchanged)
[see `PROBLEM_ANCHOR.md`]

## Anchor Check
- Bottleneck unchanged.
- Revised method still addresses it — in fact, more directly now that synthetic errors are forbidden from the main table.
- Reviewer suggestions rejected as drift: **none**. Reviewer correctly caught that the R2 fallback ("supplement with Fuzzlang-Transformer-generated errors on post-cutoff commits, labeled") would itself be drift, since the anchor specifies real errors from real projects. Mitigation removed.

## Simplicity Check
- Dominant contribution unchanged.
- Components removed/merged: HPC column dropped from main table (stays in appendix); mitigation-path for sparse naturals replaced with explicit scope-shrink rule; notes + B3 remain appendix.
- Why still smallest adequate: nothing added; two things removed (synthetic-pad mitigation, HPC main column).

## Changes Made

### 1. Hard rule: main table = natural compiler errors from real projects only
- **Reviewer said**: R3 Item 1 (only blocker).
- **Action**: add a paper-level rule, stated up front in the evaluation section:
  > **Evaluation-Purity Rule.** The main table reports only natural compilation errors collected from real C/C++ projects post 2024-10-01. Synthetic errors (Fuzzlang-Transformer mutations) may appear in (a) training data for the B2/B3 SFT baselines, and (b) appendix stress tests. They may never appear in the main table.
- **Impact**: removes the last pseudo-novelty risk; makes the headline numbers audit-proof against "it's just mutation classification".

### 2. Pre-specified harvesting and dedup protocol for natural errors
- **Reviewer said**: R3 Item 2.
- **Action**: formalize the natural-error harvest into a pipeline called **NatErr**, with fixed sources, filters, and dedup rules:

  **Sources (post 2024-10-01)**:
  - **S1: Git-history fault harvest** — for a fixed list of open-source C/C++ projects (LLVM itself, Chromium, FFmpeg, LibreOffice, PostgreSQL, Blender, Qt, Bitcoin Core — all large, active, post-2024-10-01), walk commit history, identify *fix-build* commits (commit message matches `/fix.*build|fix.*compil|unbreak.*build/i` or parent CI was red), check out the *predecessor* commit, attempt to build under the project's declared CI configuration. If compile fails, that failure is a natural error.
  - **S2: Public CI failure logs** — scrape GitHub Actions / Buildbot logs from the same project set; filter to compile-error failures post 2024-10-01.
  - **S3: LLVM/Clang `llvm-lit` test corpus** — *excluded* from main evaluation on the purity-rule reading (Clang's own test-case errors are curated, not natural production errors). Used only as held-in SFT data for B2/B3 and for Fuzzlang Agent's reproduction workflow.

  **Filters**:
  - F1: error must be a genuine compilation error (Clang diag severity = `error`), not a warning-as-error upgrade.
  - F2: error must reproduce under a publicly documented compile command (either from CI log or from project's declared build files).
  - F3: error's originating commit SHA must be > 2024-10-01.
  - F4: no inclusion of commits that the user / co-authors of this paper authored.

  **Dedup** (train ↔ eval):
  - D1: AST-hash dedup on a 5-line window around the error span against any Fuzzlang-LLVM training instance.
  - D2: `(diag_id, normalized_source_snippet)` tuple dedup within the eval split itself.
  - D3: project-level disjointness for the HPC slice (HPC eval projects must not appear in training).

  **Target size**: 3000 instances for the main split; 500 for the HPC slice.

  **Audit artifact**: a manifest file listing every eval instance's `(project, commit_sha, source_file, line, diag_id)` is released alongside the paper, so reviewers can verify purity.

- **Impact**: the eval split is now audit-proof and reproducible by a third party.

### 3. Scope-shrink rule replaces synthetic-pad fallback
- **Reviewer said**: R3 Item 3 — if naturals too sparse, shrink the claim, don't pad.
- **Action**: replace the R2 risk mitigation with an **explicit decision tree** for W2, evaluated against the NatErr pipeline output:

  | Natural errors collected (post W2) | Action |
  |---|---|
  | ≥ 3000 | Proceed with full-scope Claim 1. |
  | 1000 – 2999 | Proceed, but explicitly label the paper "Diagnostic-Verified Code Repair at 1k Scale" and discuss scale limits. |
  | 300 – 999 | Narrow scope to a single project (e.g., LLVM self-hosting) for Claim 1; reframe as depth study, not coverage study. |
  | < 300 | Halt submission; the anchor problem is real but the evidence bar cannot be met; escalate to user rather than pad. |

- **Impact**: the paper has a principled failure-recovery path that never violates the anchor.

### 4. HPC column dropped from main table, moved to appendix
- **Reviewer said**: Simplification #2 — drop HPC from main unless clearly additive.
- **Action**: HPC slice remains in the proposal but is reported as an **appendix-only** result. If it is exceptionally strong (DVCR lift > 30 pp on OpenMP+OpenACC), the paper's introduction may cite it as a motivating case study; otherwise it stays in appendix as a "domain robustness" check.
- **Impact**: Claim 2 demoted from "supporting column" to "appendix case study". Paper identity = single-claim method paper. Reduces "domain slice" dilution the reviewer had flagged in R1.

### 5. Claim 2 reframed (paper identity follow-up)
- Previous Claim 2 ("HPC repair lift") → **"Domain robustness: DVCR preserves its lift on directive-parallel compilation errors (OpenMP, OpenACC)."** Appendix only. Not a co-equal claim.

---

## Revised Proposal (round-3 — this should reach READY)

### Title
**Diagnostic-Verified Code Repair: Typed Compiler Diagnostics as an Inference-Time Verifier for LLM Repair**

### Headline (locked, unchanged)
*Typed compiler diagnostics used as an inference-time verifier signal produce measurably better compilation-error repair than stderr-text feedback and than static supervised fine-tuning, under project-level-isolated evaluation and at matched inference budgets, on natural C/C++ compilation errors from real projects.*

(Removed "and directive-parallel (OpenMP/OpenACC) code" from the headline — that domain becomes appendix robustness, not headline scope.)

### Problem Anchor
[verbatim; unchanged]

### Technical Gap
[unchanged — three failure modes; intervention = diag_id in the inference-time loop]

### Contribution Focus
- **Dominant**: DVCR inference-time agent with 488-class typed diag_id as a first-class observation.
- **Non-contributions**: Fuzzlang-LLVM dataset; fine-tuning recipes; evaluation-protocol methodology; HPC/multi-compiler/multi-scale/multi-search.

### Evaluation-Purity Rule (new, headline-level)
> The main evaluation table reports only natural compilation errors collected post-2024-10-01 from real C/C++ projects, harvested via the pre-specified NatErr pipeline (S1 git-history fault harvest + S2 CI failure scrape; see below). Synthetic errors from Fuzzlang Transformer are used only (a) for B2/B3 SFT baseline training and (b) for appendix stress tests. They never appear in the main table.

### Proposed Method — Complexity Budget

**Frozen / reused**: modified Clang; modified `diagtool`; Fuzzlang Transformer (offline, B2/B3 training only); Fuzzlang Agent (offline, B2/B3 training-data curation from `llvm-lit`); Qwen2.5-Coder-32B-Instruct.

**New (inference-side only)**:
1. **Verifier V**: subprocess shim around modified Clang with **primary-diagnostic-only rule**. Out `{status, diag_id, diag_name, diag_msg, file, line, col, span}`. Cached. ~250 LoC.
2. **Agent π**: one LLM call per turn per branch. Structured prompt fields: span-windowed snippet, diag_id, diag_name, diag_msg, **last 2 turns** of trajectory. JSON-schema-constrained output `{start_line, end_line, replacement}` with ±L=5 line window. ~400 LoC.
3. **Search**: parallel K=4 proposals at temp 0.8; verifier picks first OK + shortest edit; else advance all. Budget T=5.
4. **Terminal**: `status == OK` at original cmd AND whole-file re-compile no regressions. Trivial-deletion guard.
5. **Dead-end**: `span_hash = sha256(diag_id || "|" || normalized_file_path || "|" || start_byte_offset || "|" || end_byte_offset || "|" || whitespace_normalized(snippet))`. Same two turns → kill branch, respawn temp 1.0. All K dead-end on same span_hash after T → FAIL.

**Not used**: multi-file navigation; error-type classifier; retriever; RL; beam/majority/greedy.

### Core Mechanism
State `s_t = (src_t, diag_id_t, diag_name_t, diag_msg_t, span_t, traj_{<t}[-2:])`.
Action `e_t = JSON{start_line, end_line, replacement}`, span-windowed.
Policy π: structured-output LLM call.
Transition deterministic.

### Integration Into Fuzzlang Infra
- Eval-time: harness feeds `(natural_buggy_src, compile_cmd)` from NatErr split; DVCR calls V only.
- Training-data time (B2/B3 only): Fuzzlang Transformer mutates LLVM source offline; Fuzzlang Agent reproduces errors from `llvm-lit`. Both feed only B2/B3 SFT training, never the main eval split.

### NatErr Pipeline (new, evaluation-side)

**Sources (post 2024-10-01)**:
- **S1 — Git-history fault harvest**: fixed project list {LLVM, Chromium, FFmpeg, LibreOffice, PostgreSQL, Blender, Qt, Bitcoin Core}. Walk commits, flag *fix-build* commits (commit-message regex + CI-red signal), check out predecessor, attempt build under CI config, collect compile failure.
- **S2 — Public CI failure logs**: scrape GitHub Actions / Buildbot for same project set, filter to compile-error failures post 2024-10-01.
- **S3 (excluded from main)**: `llvm-lit` curated tests; used only for B2/B3 training and for Fuzzlang Agent reproduction.

**Filters**: error severity = `error`; reproducible under documented cmd; commit SHA > 2024-10-01; not authored by this paper's authors.

**Dedup (train ↔ eval)**: AST-hash on 5-line window against Fuzzlang-LLVM training; `(diag_id, normalized_snippet)` internal dedup; project-level disjointness for HPC.

**Target size**: 3000 main + 500 HPC (appendix).

**Scope decision tree**:
| Naturals collected | Action |
|---|---|
| ≥ 3000 | Full Claim 1. |
| 1000–2999 | Claim 1 with explicit scale label. |
| 300–999 | Narrow to single-project depth study. |
| < 300 | Halt; escalate to user. |

**Audit artifact**: released manifest of `(project, commit_sha, source_file, line, diag_id)` per instance.

### Validation

#### Claim 1 (MAIN, one table, 4 rows)

| Method | verified_fix_rate@T=5 | tokens |
|---|---|---|
| B0 zero-shot | — | matched |
| B1 stderr-loop | — | matched |
| B2 static SFT | — | matched |
| **DVCR (ours)** | — | matched |

All on NatErr main split. Metric: verified_fix_rate@T=5 with 95% bootstrap CI.

#### Causal Ablations (MAIN: 3-way signal + 1 loop-off)

| Ablation | Observation | Isolates |
|---|---|---|
| DVCR (full) | `{diag_id, diag_name, diag_msg, span}` | — |
| **DVCR − id** | `{diag_name, diag_msg, span}` | Typed ID on top of structure |
| **DVCR − structure** | raw stderr | Structured interface in general |
| **DVCR − loop** | full obs, T=1 | Loop |

#### Contamination Floor
Base-model verified_fix_rate on NatErr main split, reported pre-intervention. Independent of any cutoff claim.

#### Appendix
- **HPC robustness**: DVCR vs B1 vs B2 on OpenMP+OpenACC slice (S1 subset on HPC projects — not `llvm-lit`).
- **B3 = SFT + stderr-loop**.
- Notes/macro/template-chain inclusion variant.
- Trajectory trim 1 / 2 / full.
- GCC cross-compiler transfer.
- Qwen2.5-Coder-7B robustness.
- DTFT sanity-check (one row).
- Budget T ∈ {1,2,3,5,10} sensitivity.
- Per-diagnostic-family table.
- Synthetic stress test: run DVCR and baselines on Fuzzlang-Transformer-generated errors to demonstrate where the natural-only number sits relative to synthetic-benchmark numbers.

### Compute & Timeline

**Compute**: Main ~500 GPU-hrs on Qwen2.5-Coder-32B. HPC appendix ~50. Verifier farm ~500 core-hrs. Appendix +200-400 GPU-hrs.

**Timeline**:
- W1 Scaffolding (~600 LoC) + NatErr pipeline (~300 LoC).
- W2 **Run NatErr pipeline**. Assess yield. Apply scope decision tree. Lock train/eval dedup.
- W3 Main table + 3-way ablation + loop-off. Contamination floor.
- W4 Appendix experiments: HPC robustness, B3, GCC, 7B, budget sweep, DTFT, per-family. Draft skeleton.
- W5 Paper draft.
- W6 External review loop + revision.
- +1 wk slack.

### Handoff Must-prove
1. DVCR > B1 at matched budget on NatErr main.
2. DVCR > B2 at matched budget.
3. DVCR > DVCR−id at matched budget (typed-ID causal).

### Highest risks
1. Qwen2.5-Coder cutoff undocumented → contamination floor is the ground truth (unchanged mitigation).
2. **NatErr yield too low** → scope decision tree (narrow, not pad). No synthetic supplementation.
3. DVCR ≈ DVCR−id → honest report; thesis weakens to "structured inference-time compiler verifier"; anchor still solved.
