# Round 6 Initial Proposal (v2 cycle)

> Opening new cycle. Rounds 1-4 produced READY at 9.2/10 but under a
> paraphrased reading of the OOPSLA critique. Now we have the verbatim
> reviews (`refine-logs/OOPSLA_REVIEWS.md`) and empirical Stage 2 yield
> (873 raw candidates → projected 260-540 usable, borderline anchor halt).
> This round reopens Phase 1 with a revised proposal that addresses each
> of the 12 reviewer-derived concerns.

## Problem Anchor
[verbatim from `PROBLEM_ANCHOR.md`, including the 2026-04-23 evidence-standard addendum]

## Technical Gap (unchanged)

Three failure modes in current LLM compile-error-repair pipelines:
1. Static SFT pipelines (Fuzzlang v1, OpenCodeInterpreter, HPC-Coder-v2): accuracy collapses under rigorous data isolation because mutation-generated train/test pairs are near-duplicate.
2. Execution-feedback agents (Self-Debug, Reflexion, SWE-agent, Agentless, RLEF): feedback is pass/fail or free-form stderr.
3. LLM compiler fuzzing (Fuzz4All, WhiteFox): orthogonal — uses compiler to find compiler bugs, not to repair user code.

Smallest adequate intervention: put the diag_id in the inference loop as a typed verifier observation.

## Method Thesis (unchanged)

Typed compiler diagnostics used as an inference-time verifier signal produce measurably better compilation-error repair than stderr-text feedback and than static supervised fine-tuning, **under both rigorous mutation-based and natural-error evaluation**, at matched inference budgets.

## Contribution Focus (unchanged)

- Dominant: DVCR inference-time agent with 488-class typed diag_id as first-class observation.
- Explicit non-contributions: Fuzzlang-LLVM dataset; fine-tuning recipes; evaluation-protocol methodology; HPC/multi-compiler/multi-scale.

## Proposed Method — Complexity Budget (unchanged structure)

Frozen / reused: modified Clang with diag-ID emission (Patch 1); stock diagtool; Fuzzlang Transformer wrapper (now used for **both** B2 training data AND one column of eval); Fuzzlang Agent pipeline (eval-curation only); Qwen2.5-Coder-7B-Instruct (main) + 32B (appendix) + Llama-3.3-70B-Instruct (appendix scale calibration) + GPT-5 or Claude-4.5 API (appendix frontier calibration, single-seed, optional).

New (inference-side, unchanged from Round 4):
1. Verifier V with primary-diagnostic rule + stable logical path.
2. Agent π with JSON-schema-constrained edit action, span window L=5, last-2-turn trajectory.
3. Parallel sampling K=4 + verifier-select loop, T=5.
4. Terminal + trivial-deletion guard + span_hash dead-end detection.

## Evaluation — revised

### Two-column main table (replaces natural-only main table from Round 4)

Both columns evaluated at matched Qwen2.5-Coder-7B + matched output-token envelope + compiler-only oracle. Each method reported on both columns.

**Column A — Mutation-based eval (project-level holdout):**
- Train side uses Fuzzlang-Transformer mutations on project set **X** = {LLVM}.
- Eval side uses Fuzzlang-Transformer mutations on project set **Y** = {PostgreSQL, FFmpeg, Qt, Blender} — strictly disjoint from X.
- AST-hash dedup enforced across X↔Y boundary so no near-duplicate can bridge the split.
- Within Y, further stratify eval by diagnostic family (held-out families for generalization check).
- Target size: 3000 eval instances from Y.
- **This column directly answers Reviewer C's "same codebase" objection AND supports the scale the headline claim needs.**

**Column B — Natural-error eval (NatErr):**
- Eval instances from NatErr Stage 2 reproduction of fix-build commits on the 8 NatErr projects, all commits ≥ 2025-06-01.
- No training data from NatErr anywhere — it is eval-only.
- Size: whatever Stage 2 yields (projected 100-500 usable). Reported at actual scale.
- **This column directly answers Reviewer B's "evaluation relies entirely on synthetic errors" AND grounds the realness claim.**

**Main table rows (repeats for each of Columns A and B):**

| # | Method | Description |
|---|---|---|
| B0 | zero-shot | Single LLM call, stderr observation, no loop, no SFT. |
| B1 | stderr-loop | T=5 K=4, stderr-text observation, no structured diag fields. |
| B2 | static SFT | LoRA on Fuzzlang-LLVM mutations of X, then single-shot inference. |
| B3 | SFT + stderr-loop | B2 policy + B1's loop. (Appendix in Round-4; promoted to main given Reviewer B's comparison-baseline ask.) |
| **B_classical** | **DrRepair** | **NEW.** Prior-era compile-error repair system (Yasunaga & Liang 2020, ICML) applied to both columns. Serves as a classical-repair-family comparator per Reviewer B. |
| **DVCR** | **ours** | Loop + typed diag-ID + JSON edits. Full signal. |

### Causal ablations (Main, 3-way signal + 1 loop-off, unchanged from Round 4)

| Ablation | Observation | Isolates |
|---|---|---|
| DVCR (full) | `{diag_id, diag_name, diag_msg, span}` | — |
| DVCR − id | `{diag_name, diag_msg, span}` | Typed ID on top of structure |
| DVCR − structure | raw stderr | Structured interface in general |
| DVCR − loop | full obs, T=1 | Loop |

Run on Column A (primary, enough power); Column B sample if yield permits. Answers Reviewer C's "how much does ID help beyond raw error messages?" directly.

### Methodology section (§, explicit per Reviewer A + C)

One subsection in the paper answers the split-mechanics question directly:

1. **Cross-project holdout.** Projects X (train) and Y (eval) are disjoint. Listed by name.
2. **AST-hash dedup.** For each eval instance, compute `AST-hash(ctx_5_lines_around_span)`; reject if this hash appears in the train set. Enforces "no same function, no same fuzzing rule applied to same span."
3. **Temporal holdout for NatErr.** Eval commits strictly ≥ 2025-06-01, beyond Qwen2.5-Coder's training cutoff buffer.
4. **Contamination floor.** Pre-intervention base-model `verified_fix_rate` on eval is reported. All gains reported relative to floor.
5. **Compiler oracle.** Success iff (a) compile OK under the original compile_cmd AND (b) whole-file re-compile introduces no new error AND (c) trivial-deletion guard passes.
6. **No LLM judge.** Documented as a hard rule, everywhere.

### Appendix experiments

Promoted to appendix (all optional but strongly recommended):

- **HPC robustness**: OpenMP/OpenACC subset (domain transfer). 500 instances.
- **Scale calibration**: Qwen2.5-Coder-32B, Llama-3.3-70B, and optional GPT-5 / Claude-4.5 single-seed calibration — establishes that the mechanism effect survives at larger scale (addresses Reviewer B #1).
- **GCC cross-compiler transfer**: sanity that it is not a Clang-only trick.
- **Notes / macro / template-chain inclusion variant**: does the primary-diagnostic-only rule cost us?
- **Trajectory trim**: 1 / 2 / full turns.
- **Budget sensitivity T ∈ {1,2,3,5,10}**.
- **Per-diagnostic-family table**.
- **DTFT sanity row**: does LoRA on DVCR trajectories add anything? Probably not; we want to show it.
- **Limitations / safety analysis (NEW, per Reviewer B):**
  - A subset of eval instances that have an associated test suite (e.g., PostgreSQL `regress`, FFmpeg `fate`) is run through DVCR, and we report `(compile_ok ∧ tests_pass_rate)` as a secondary metric — the true "semantic fix rate" proxy.
  - We expect this subset to show a gap: some compile-only successes are semantic regressions. We report the gap honestly.
  - Case studies of 3-5 "successes" where the repair is wrong.

### Data + code availability (NEW, per Reviewer A + C)

At camera-ready:
- Fuzzlang-v2 repo on GitHub (this branch, cleaned).
- NatErr manifest (audit artifact) on HuggingFace.
- Both eval splits (Columns A and B) on HuggingFace.
- Patched-clang binary (LLVM 19.1.7 + Patch 1) as a release asset.
- Seeds + exact PBS submission scripts.

## Claim-Driven Validation

### Claim 1 (MAIN): Two-column cross-regime effect
At matched base model + matched token budget, DVCR beats B0/B1/B2/B3/B_classical on **both** Column A (mutation, N=3k, project-level holdout) **and** Column B (natural, N=whatever).

- Success: DVCR > B1 by ≥ 5 pp with non-overlapping 95% bootstrap CI on Column A (primary, high-power). Same direction on Column B even if CI looser.
- Failure: DVCR on par with B1 on Column A → mechanism claim dead.

### Claim 2 (CAUSAL): Typed-ID vs structured-but-untyped
DVCR > DVCR − id ≥ 3 pp with non-overlapping CI on Column A.

### Claim 3 (ROBUSTNESS, optional): Scale + domain transfer
Scale calibration rows + HPC subset show DVCR lift persists.

## Compute & Timeline

**Compute (Polaris A100-40GB, `diomp`, 150 node-hour budget)**:
- Column A sweep (5 methods + DVCR + 4 ablations = 10 rows × 3 seeds × 3000 instances × T=5 K=4): ≈ 80 node-hours on Qwen2.5-Coder-7B (within budget).
- Column B sweep (same 10 rows × 3 seeds × ≤500 instances): ≈ 15 node-hours.
- B2 LoRA SFT on X: ~8 node-hours.
- DrRepair classical baseline: runs on CPU mostly; trivial.
- 32B / 70B appendix: ~30 node-hours (selective cells).
- Frontier API calibration: no Polaris cost; API credits only.
- Total projected: ~130 node-hours. Fits 150 budget with ~20 hours slack.

**Timeline (5-week NeurIPS 2026 track)**:
- W1: (a) finish Fuzzlang-Transformer project-set split infra; (b) integrate DrRepair into baseline registry; (c) complete NatErr Stage 2 LLVM driver; (d) scale calibration env.
- W2: Column A primary run + causal ablations.
- W3: Column B primary run. Limitations/safety subset run. Scale-calibration rows (32B, 70B, frontier).
- W4: All other appendix experiments (HPC, GCC, trajectory, etc.). Writing skeleton.
- W5: Paper draft + external review loop. Buffer.

## Experiment Handoff Inputs

**Must-prove claims**:
1. DVCR > B1 on Column A at matched budget with non-overlapping CI.
2. DVCR > B1 on Column B (direction, even if CI looser).
3. DVCR > DVCR − id on Column A.
4. DVCR > B_classical (DrRepair) on both columns.

**Highest risks**:
1. NatErr Stage 2 yield < 100. Mitigation: the two-column design makes Column B optional for the headline claim; DVCR can rest on Column A alone as the contamination-rigorous evaluation if Column B is underpowered. Explicitly call this out in the paper.
2. DrRepair fails to compile in modern env. Mitigation: allot 3 days of eng; if unsalvageable, substitute MACER (Pu et al. 2019) or Break-It-Fix-It (Yasunaga & Liang 2021) — all from same family.
3. Scale calibration (70B / frontier) shows DVCR's gap closes at large scale. Mitigation: this is legitimate empirical finding; headline becomes "DVCR is a small-model enabler" which is still interesting.
