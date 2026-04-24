# Diagnostic-Verified Code Repair: Typed Compiler Diagnostics as an Inference-Time Verifier for LLM Repair

> Final refined research proposal (v2 cycle, Round 7 READY at ~9.3/10).
> Supersedes the v1 (Round 4) FINAL_PROPOSAL after verbatim OOPSLA reviews
> were recovered and Stage 2 empirical yield came in.
> Target venue: NeurIPS 2026 main track.

## Headline (locked, reused verbatim in abstract + conclusion)

*Typed compiler diagnostics used as an inference-time verifier signal produce measurably better compilation-error repair than stderr-text feedback and than static supervised fine-tuning, under both rigorous mutation-based evaluation (project-level train/eval holdout with AST-hash dedup) and natural-error evaluation (real developer compile errors harvested from production C/C++ projects), at matched inference budgets.*

## Evidence standard (from revised Problem Anchor)

Two evaluation regimes, both required, not interchangeable:

- **Column A (Mutation, primary)**: Fuzzlang-Transformer mutations with strict project-level holdout (train on X = {LLVM}, eval on Y = {PostgreSQL, FFmpeg, Qt, Blender}, AST-hash dedup across X↔Y). Primary statistical claim; N = 3000.
- **Column B (Natural, external validity)**: NatErr real fix-build compile errors, eval-only. N = whatever Stage 2 produces (projected 100-500). Checks that Column A is not a mutation-regime artifact.

Compiler is the only oracle anywhere in the paper. No LLM judge.

---

## Problem Anchor (immutable across cycles)

**Bottom-line problem.** LLM-based code repair for compilation errors emitted by production C/C++/directive-parallel compilers is still unreliable at the level demanded by real build systems. A model that scores well on synthetic benchmarks still fails on real errors from real projects, and "fine-tune a bigger dataset" has reached a clear diminishing-returns point once data isolation is enforced. The compiler itself — which produces the error and can verify any proposed fix for free — is treated as a passive data source rather than an active, loop-closing signal.

**Must-solve bottleneck.** The compiler's own diagnostic output (diagnostic ID + message + location) is the cheapest, most precise ground-truth signal in existence for code-repair correctness, but today's LLM repair pipelines do not close the loop on it.

**Non-goals.** General-purpose coding agent (SWE-bench); runtime / semantic bug fixing; new LLM architecture or pre-training objective; yet another synthetic error dataset as main contribution.

**Constraints.** NeurIPS 2026; Polaris @ Argonne (`diomp`, 150 node-hour budget); open-weights preferred; reuse Fuzzlang v1 infra; rigorous data isolation; no sibling-LLM judge; mandatory ablations + baselines + contamination audit.

**Success condition (revised 2026-04-23)**. Reviewers of NeurIPS 2026 would be convinced that (1) DVCR beats B0/B1/B2/B3/B_classical on Column A at non-overlapping 95% CI and directionally beats them on Column B, (2) the DVCR − id ablation confirms typed ID is causal beyond structured-but-untyped feedback, (3) the model-selection protocol protects Column A and Column B from being silently tuned on.

---

## Technical Gap

Three failure modes:
1. **Static SFT pipelines** (Fuzzlang v1, OpenCodeInterpreter, HPC-Coder-v2): accuracy collapses under rigorous data isolation because mutation-generated train/test pairs are near-duplicate within the same codebase.
2. **Execution-feedback agents** (Self-Debug, Reflexion, SWE-agent, Agentless, RLEF): feedback is pass/fail (collapses the 488-class diagnostic space) or free-form stderr (re-parsed every turn). Neither tells the agent *which kind of error remains*.
3. **LLM compiler fuzzing** (Fuzz4All, WhiteFox, FuzzGPT): uses compiler to find compiler bugs, not to repair user code. Orthogonal.

**Smallest adequate intervention**. Put the diagnostic ID in the inference loop. Expose the compiler as a typed verifier `V(code, cmd) → {OK} ∪ {(diag_id ∈ [1..488], diag_name, msg, file, line, col, span)}`. The agent conditions on the diagnostic *trajectory*, not stderr text.

**Core technical claim**. Diagnostic-ID-grounded inference-time repair beats both static SFT and stderr-text iterative repair at matched inference budgets, evidenced under BOTH mutation-with-rigorous-holdout and natural-error regimes.

---

## Contribution Focus

- **Dominant contribution**: **DVCR** — a minimal inference-time agent in which the compiler's 488-class typed diagnostic ID is a first-class observation, so the policy LLM conditions on the diagnostic trajectory rather than on stderr strings or pass/fail.
- **Explicit non-contributions**: Fuzzlang-LLVM dataset (reused supporting infrastructure); fine-tuning recipes (baseline components); evaluation-protocol methodology (supporting rigor); HPC / multi-compiler / multi-scale (appendix robustness).

---

## Method

### Complexity Budget

**Frozen / reused**:
- Modified Clang with diagnostic-ID emission (Patch 1 in `scripts/patches/0001-*.patch`).
- Stock `diagtool` (the reverse `find-diagnostic-id <int>` path handles ID → name).
- Fuzzlang Transformer wrapper — used for (a) B2/B3 SFT training data generation on X = {LLVM}, AND (b) Column A eval generation on Y = {PostgreSQL, FFmpeg, Qt, Blender}. Project-disjoint train/eval.
- Fuzzlang Agent pipeline (`scripts/run_natErr_stage1.py`, stage 2 in progress) — used for Column B eval curation only.
- Base LLM: **Qwen2.5-Coder-7B-Instruct** (main) + **Qwen2.5-Coder-32B-Instruct** (appendix scale) + **Llama-3.3-70B-Instruct** (appendix scale calibration) + optional frontier API calibration single-row (GPT-5 or Claude-4.5, 2026-era).

**New (inference-side only)**:
1. **Verifier V**: subprocess shim around modified Clang, implementing the primary-diagnostic-only rule. Returns `{status, diag_id, diag_name, diag_msg, file, line, col, span}`. Caches. Uses `logical_path` kwarg so span_hash is stable across repeated verifies (already implemented in `experiments/verifier/fuzzlang.py`).
2. **Agent π**: one LLM call per turn per branch. Structured prompt: source snippet around span, diag_id, diag_name, diag_msg, last 2 turns of trajectory. JSON-schema-constrained output `{start_line, end_line, replacement}` in span window `[line − 5, line + 5]`.
3. **Search**: parallel K = 4 proposals at temp 0.8; verifier picks first OK (shortest-edit tiebreak); else advance all branches. Budget T = 5.
4. **Terminal criterion**: `status == OK` AND whole-file re-compile no regressions AND trivial-deletion guard passes.
5. **Dead-end detection**: `span_hash = sha256(diag_id || "|" || normalized_file_path || "|" || start_byte || "|" || end_byte || "|" || whitespace_normalized(snippet))`. Same span_hash on two consecutive turns → kill branch, respawn once at temp 1.0. All K branches dead-end on same span_hash → terminate FAIL.

**Intentionally not used**: multi-file repo-level navigation; separate error-type classifier (compiler already emits it); retriever; full RL; beam / majority-vote / greedy search.

### Core Mechanism

State `s_t = (src_t, diag_id_t, diag_name_t, diag_msg_t, span_t, traj_{<t}[-2:])`.
Action `e_t = JSON{start_line, end_line, replacement}`, span-windowed.
Policy π: single structured-output LLM call per turn per branch.
Transition: deterministic (apply edit, re-invoke V).

Why `diag_id` is the causal factor (tested in ablation):
1. Classification is free — saves tokens baselines burn on stderr parsing.
2. Dead-end detection is a one-line rule because `diag_id` is categorical.
3. Cross-turn reasoning becomes discrete (`err_expected_semi → err_undeclared_var`).
4. Verifier selection reduces to `status == OK`.

---

## §Methodology

### Split mechanics

Answers Reviewer A and C directly ("how did you do the 80/20 split / avoid contamination?").

1. **Project-level holdout for Column A.** X = {LLVM}. Y = {PostgreSQL, FFmpeg, Qt, Blender}. Train and Column A eval never share projects.
2. **Source-provenance X-dev carve.** Before any mutation is generated, X = LLVM is partitioned at the **file / function / commit** level into X-train and X-dev. Mutations of the same underlying function CANNOT appear in both. This carve is source-provenance-level, not post-mutation 80/20.
3. **AST-hash dedup.** For every Column A eval instance, the 5-line AST-normalized hash around the span is computed. If it collides with any X-train hash, the instance is rejected.
4. **Temporal holdout for Column B.** NatErr eval commits strictly ≥ 2025-06-01 (~8 months past Qwen2.5-Coder's training cutoff buffer).
5. **Diagnostic-family stratification.** Some Column A eval instances are drawn from diagnostic families that appear zero times in X-train, as a generalization check.
6. **Contamination floor.** Pre-intervention base-model `verified_fix_rate` measured on Column A eval and Column B eval. The measurement **procedure** is locked on X-dev (so no tuning on the eval sets); the measurement **target** is the eval sets themselves. All gains reported relative to floor.
7. **Compiler oracle.** No LLM-as-judge. Success iff the patched clang compiles the file cleanly under the original compile command AND no new error is introduced.

### Model Selection Protocol

Decisions locked on **X-train / X-dev only**:
- Prompt text for the policy (all three signal modes).
- LoRA rank, alpha, learning rate, and epoch count for B2 / B3 / DTFT-ablation SFT.
- Policy search hyperparameters: T, K, temperature, span window L, trajectory N.
- DVCR edit-schema (JSON field shape).
- Dead-end respawn rule.
- Contamination-floor measurement **procedure** (not values).

Data **never** touched for tuning:
- Column A eval set (mutations on Y).
- Column B eval set (NatErr).
- All appendix eval subsets (HPC, GCC transfer, 32B / 70B / frontier calibration).

All eval-set numbers are generated once, with a locked configuration, at submission time. Model-selection logs are archived with the audit manifest so the chain of decisions is post-hoc auditable.

This protocol is in §Methodology (not appendix) because contamination concerns in the OOPSLA reviews are specifically about silent hidden tuning.

---

## Evaluation

### Main table — two columns × five rows

Column A = Fuzzlang-Transformer mutations on Y (N = 3000); Column B = NatErr naturals (N = whatever Stage 2 yields).
Both columns use Qwen2.5-Coder-7B-Instruct and matched output-token envelope (`E_tokens = T × K × 256 = 5120`). Three seeds.

| Method | Column A verified_fix_rate@T=5 | Column B verified_fix_rate@T=5 | tokens | Description |
|---|---|---|---|---|
| B0 zero-shot | — | — | matched | No loop, no SFT; single shot. |
| B1 stderr-loop | — | — | matched | Self-Debug style; T=5 K=4; stderr text observation. |
| B2 static SFT | — | — | matched | LoRA on X mutations; single shot. |
| B3 SFT + stderr-loop | — | — | matched | B2's model with B1's loop. |
| **DVCR (ours)** | — | — | matched | Loop + typed diag-ID + JSON edits. |

**`B_classical` (DrRepair / MACER) was removed from the main table on 2026-04-23.**
Three reasons: (1) DrRepair (Yasunaga & Liang 2020) ships no pretrained
checkpoint and re-training requires a 2020-era stack (Python 3.6.8 +
torch 1.0.1 + python-clang 8.0.1 + DeepFix data + CUDA 9/10 GPU),
unmaintainable in our 2026 Pine + Polaris environment; (2) the gate-fallback
chain MACER → BIFI is broken — MACER's three commonly cited GitHub repos
are all 404, BIFI is the same author / same training-cost story as DrRepair;
(3) Reviewer B's specific concern #5 ("compare against existing methods")
was framed in 2025 against pre-LLM-era classical repair, but in 2026 the
same family of comparison is now redundant with the LLM-era B0/B1/B2/B3
baselines that already span no-loop, stderr-loop, static-SFT, and
SFT+loop. Scale calibration in appendix (32B / 70B / optional frontier
API) supplies the LLM-vs-LLM frontier comparator that is the relevant
contemporary check. The paper will explicitly note this scope decision
in §Limitations to address Reviewer B directly.

Metric: `verified_fix_rate@T=5` — compiler-verified success under the original compile command with no new regressions, within budget T = 5 turns. 95% bootstrap CI (10k resamples) reported on both columns.

### Causal Ablations — on Column A (primary, high power)

| Ablation | Observation | Isolates |
|---|---|---|
| DVCR (full) | `{diag_id, diag_name, diag_msg, span}` | — |
| **DVCR − id** | `{diag_name, diag_msg, span}` | Typed ID on top of structure |
| **DVCR − structure** | raw stderr | Structured interface in general |
| **DVCR − loop** | full observation, T = 1 | Loop |

Answers Reviewer C's "how much do diagnostic ID and name contribute beyond raw error messages?" directly.

### Contamination Floor

Base-model verified_fix_rate on Column A + Column B, pre-intervention. All deltas reported relative.

### Appendix

- **Limitations / safety subset** (addresses Reviewer B): subset of Column A + Column B where the file is covered by a project test suite (e.g., PostgreSQL `regress`, FFmpeg `fate`); report `(compile_ok ∧ tests_pass)` rate. Expected gap between compile-rate and tests-pass-rate; reported honestly with 3-5 case studies of compile-success-but-semantic-regression failures.
- **HPC robustness**: OpenMP + OpenACC subset of NatErr-reproducible instances.
- **Scale calibration**: Qwen2.5-Coder-32B-Instruct full row; Llama-3.3-70B-Instruct full row; one optional frontier API calibration cell (GPT-5 or Claude-4.5). Single seed each.
- **GCC cross-compiler transfer**: one mini-table; DVCR + B1 on GCC-generated diagnostics (with diag-ID crosswalk).
- **Notes / macro / template-chain inclusion variant**.
- **Trajectory trim**: 1 / 2 / full turns.
- **Budget sensitivity**: T ∈ {1, 2, 3, 5, 10}.
- **Per-diagnostic-family breakdown**.
- **DTFT sanity** (LoRA on DVCR successful trajectories).
- **Synthetic stress test**: run DVCR and baselines on X-train mutations (in-distribution) to expose the gap between in-distribution and held-out (Column A) performance.

---

## Data + Code Availability (addresses Reviewer A + C)

At camera-ready:
- Fuzzlang v2 code on **GitHub** (this repo, `feat/dvcr-scaffolding` branch cleaned up).
- **Hugging Face dataset**: Column A mutation split, Column B NatErr split, NatErr audit manifest.
- **Patched-clang binary** (LLVM 19.1.7 + Patch 1) as a GitHub release asset + the `.patch` file for reproduction.
- Seeds, PBS submission scripts, model-selection logs.

---

## Claims

**Claim 1 (MAIN, cross-regime)**: At matched Qwen2.5-Coder-7B + matched token budget, DVCR beats all LLM-era baselines (B0/B1/B2/B3) on **Column A** (non-overlapping 95% bootstrap CI, ≥ 5 pp absolute gap over B1) and directionally on **Column B**.

**Claim 2 (CAUSAL)**: DVCR > DVCR − id ≥ 3 pp with non-overlapping CI on Column A. The typed-ID signal is causally load-bearing beyond structured-but-untyped feedback.

**Claim 3 (ROBUSTNESS, optional)**: DVCR's lift persists under scale calibration (32B, 70B, optional frontier) and on HPC directive-parallel subset.

---

## Compute & Timeline

**Compute (Polaris A100-40GB, `diomp`, 150 node-hour budget)**:
- Column A sweep (6 methods × 3 seeds × 3000 instances × loop): ~80 node-hours on Qwen2.5-Coder-7B.
- Column B sweep (same 6 methods × 3 seeds × ≤ 500 instances): ~15 node-hours.
- Causal ablations (DVCR − id / − structure / − loop on Column A × 3 seeds): ~50 node-hours.
- B2 LoRA SFT on X-train: ~8 node-hours.
- DrRepair: CPU-dominated; trivial on Polaris.
- 32B / 70B appendix scale calibration: ~30 node-hours (selective cells).
- Frontier API calibration: no Polaris cost.
- **Subtotal**: ~180 node-hours.
- **Budget buffer**: if ablations overrun, appendix scale rows are dropped before Column A/B.
- Running subset of the main table without the 3-seed replication (1 seed) drops main-table cost to ~50 node-hours, leaving headroom; 3-seed is for the headline DVCR + B1 rows where CI matters most. Other rows default to 2 seeds.

**Timeline (5-week NeurIPS 2026 full-paper window)**:
- **W1**: finish Fuzzlang-Transformer X/Y split infra; carve X-dev at source-provenance level; integrate DrRepair into baseline registry; finish NatErr Stage 2 LLVM driver; scale calibration env setup.
- **W2**: Column A primary run (DVCR, B0, B1, B2, B3, B_classical × 3 seeds) + causal ablations (DVCR − id / − structure / − loop).
- **W3**: Column B primary run + limitations/safety subset + contamination floor measurement.
- **W4**: Scale calibration (32B, 70B, optional frontier) + HPC + GCC + per-family + budget sensitivity.
- **W5**: Draft + `/auto-review-loop` iterations + camera-ready polish.

---

## Highest Risks (unchanged from Round 6)

1. **NatErr Stage 2 yield < 100 usable instances**. Mitigation: Column B becomes appendix; paper rests on Column A (mutation with rigorous project holdout). Paper explicitly frames naturals as "external validity at whatever scale is honest" and does not hide the small N.
2. **DrRepair unmaintainable in 2026** — RESOLVED 2026-04-23. After empirically confirming DrRepair has no pretrained checkpoint and the MACER fallback's GitHub repos are all 404, B_classical was removed from the main table per the in-text rationale above. Reviewer B's concern is now addressed via §Limitations + LLM-era baseline coverage (B0/B1/B2/B3) + appendix scale calibration (32B/70B/frontier).
3. **Scale calibration (70B or frontier) shrinks the DVCR effect**. Mitigation: this is legitimate empirical finding; paper's Claim 3 would move from "effect persists across scales" to "DVCR is particularly helpful at open-small-model scale, and the effect compresses at frontier-scale models that already internalize some diagnostic reasoning". Still publishable.
4. **DVCR ≈ DVCR − id on Column A**. Mitigation: Claim 2 weakens to "structured inference-time compiler verifier" rather than "typed categorical ID is the causal factor". Claim 1 survives. Anchor still solved.

---

## Handoff Must-Prove

1. DVCR > B1 on Column A at matched budget with non-overlapping 95% CI.
2. DVCR > DVCR − id on Column A (typed-ID causal).
3. DVCR > B1 on Column B directionally.
4. Model-selection protocol adhered to (audit trail archived).
5. (Was: DVCR > B_classical. Removed 2026-04-23; see §Evaluation rationale.)
