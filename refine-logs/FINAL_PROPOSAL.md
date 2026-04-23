# Diagnostic-Verified Code Repair: Typed Compiler Diagnostics as an Inference-Time Verifier for LLM Repair

> Final refined research proposal. NeurIPS 2026 main track.
> Working title; final title to be chosen at writing time.

## Headline (locked, reused verbatim in abstract + conclusion)

*Typed compiler diagnostics used as an inference-time verifier signal produce measurably better compilation-error repair than stderr-text feedback and than static supervised fine-tuning, under project-level-isolated evaluation and at matched inference budgets, on natural C/C++ compilation errors from real projects.*

## Evaluation-Purity Rule (paper-level commitment)

> The main evaluation table reports only natural compilation errors collected from commits on or after **2025-06-01** in real C/C++ projects, harvested via the pre-specified NatErr pipeline. Synthetic errors from the Fuzzlang Transformer are used only for (a) B2/B3 SFT-baseline training and (b) appendix stress tests. They never appear in the main table.

---

## Problem Anchor (immutable)

**Bottom-line problem.** LLM-based code repair for compilation errors emitted by production C/C++/directive-parallel compilers is still unreliable at the level demanded by real build systems. A model that scores well on synthetic benchmarks still fails on real errors from real projects, and "fine-tune a bigger dataset" has reached a clear diminishing-returns point once data isolation is enforced. The compiler itself — which produces the error and can verify any proposed fix for free — is treated as a passive data source rather than an active, loop-closing signal.

**Must-solve bottleneck.** The compiler's own diagnostic output (diagnostic ID + message + location) is the cheapest, most precise ground-truth signal in existence for code-repair correctness, but today's LLM repair pipelines do not close the loop on it.

**Non-goals.** General-purpose coding agent (SWE-bench); runtime / semantic bug fixing; new LLM architecture or pre-training objective; yet another synthetic error dataset as main contribution.

**Constraints.** NeurIPS 2026; Polaris @ Argonne (`diomp`); open-weights preferred; reuse Fuzzlang v1 infra; rigorous data isolation; no sibling-LLM judge; mandatory ablations + baselines + contamination audit.

**Success condition.** Reviewers accept that (1) diagnostic-ID-grounded inference-time repair beats static SFT and stderr-feedback agents; (2) the gain survives rigorous data isolation; (3) the method enables practically useful repair on HPC directive-based code where general methods fail (reported as appendix robustness).

---

## Technical Gap

Three failure modes in current pipelines:

1. **Static SFT pipelines** (Fuzzlang v1, OpenCodeInterpreter, HPC-Coder-v2): accuracy collapses under rigorous data isolation because mutation-generated train/test pairs are near-duplicate.
2. **Execution-feedback agents** (Self-Debug, Reflexion, SWE-agent, Agentless, RLEF): feedback is pass/fail (collapses the 488-class diagnostic space) or free-form stderr (re-parsed every turn). Neither tells the agent *which kind of error remains*.
3. **LLM compiler fuzzing** (Fuzz4All, WhiteFox, FuzzGPT): uses compiler to find compiler bugs, not to repair user code. Orthogonal.

**Smallest adequate intervention.** Put the diagnostic ID in the inference loop. Expose the compiler as a typed verifier `V(code, cmd) → {OK} ∪ {(diag_id ∈ [1..488], diag_name, msg, file, line, col, span)}`. The agent conditions on the diagnostic *trajectory*, not stderr text.

**Core technical claim.** Diagnostic-ID-grounded inference-time repair beats both static SFT and stderr-text iterative repair, under project-level-isolated evaluation on real C/C++ compilation errors, at matched inference budgets, using the same base LLM.

---

## Contribution Focus

- **Dominant contribution**: **DVCR** — a minimal inference-time agent in which the compiler's 488-class typed diagnostic ID is a first-class observation, so the policy LLM conditions on the diagnostic trajectory rather than on stderr strings or pass/fail.
- **Explicit non-contributions**: Fuzzlang-LLVM dataset (reused supporting infrastructure); fine-tuning recipes (appendix sanity check, one row); evaluation-protocol methodology (supporting rigor, not a co-equal contribution); HPC / multi-compiler / multi-scale / multi-search-policy (appendix).

---

## Method

### Complexity Budget

**Frozen / reused**:
- Modified Clang with diagnostic-ID emission (Fuzzlang v1 infrastructure).
- Modified `diagtool` (`find-diagnostic-name`).
- Fuzzlang Transformer wrapper (offline only, for B2/B3 SFT-baseline training data).
- Fuzzlang Agent pipeline (offline only, for B2/B3 training-data curation from `llvm-lit`).
- Base LLM **Qwen2.5-Coder-7B-Instruct** (main table and all causal ablations). **Qwen2.5-Coder-32B-Instruct** as an appendix robustness check. No from-scratch training. Choice of 7B for main: (a) fits comfortably on 1×A100-40GB for inference and 1-2×A100 for LoRA SFT on Polaris, enabling multi-seed variance reporting and rapid iteration; (b) the diag_id-as-verifier mechanism is not scale-dependent — if it works it should show at 7B; (c) direct successor to Fuzzlang v1's Llama-3-8B headline, giving a clean same-scale narrative.

**New (inference-side only)**:

1. **Verifier V**: subprocess shim around modified Clang, implementing the **primary-diagnostic-only rule** (read the first `error:` record, drop notes / macro-expansion / template-instantiation chains). Returns `{status, diag_id, diag_name, diag_msg, file, line, col, span}`. Caches by `(code_hash, cmd_hash)`. ~250 LoC.

2. **Agent π**: one LLM call per turn per branch. Structured prompt fields: source snippet around span, `diag_id`, `diag_name`, `diag_msg`, **last 2 turns** of trajectory `[(diag_id_i, edit_summary_i)]`. JSON-schema-constrained output `{start_line: int, end_line: int, replacement: str}`. Rejected if schema-invalid or outside span window `[max(0, diag.line − L), diag.line + L]` with `L = 5`. ~400 LoC.

3. **Search**: parallel `K = 4` proposals at temp `0.8` per turn; verifier picks the first `OK` with shortest-edit tiebreak; else advance all branches. Budget `T = 5`. Matched output-token envelope across all baselines.

4. **Terminal criterion**: `status == OK` at the original compile command **AND** whole-file re-compile has no new errors. **Trivial-deletion guard**: reject edits that delete non-trivial lines without replacement.

5. **Dead-end detection**:
   ```
   span_hash = sha256(
       diag_id || "|"
       || normalized_file_path || "|"
       || start_byte_offset || "|"
       || end_byte_offset || "|"
       || whitespace_normalized(snippet_at_span)
   )
   ```
   Same `span_hash` on two consecutive turns of a branch → kill the branch and respawn from parent state at temp `1.0`. All `K` branches dead-end on the same `span_hash` after `T` turns → terminate with `FAIL`.

**Intentionally not used**: multi-file repo-level navigation; separate error-type classifier (compiler already emits it); retriever; full RL; beam / majority-vote / greedy search.

### Core Mechanism

- State `s_t = (src_t, diag_id_t, diag_name_t, diag_msg_t, span_t, traj_{<t}[-2:])`.
- Action `e_t = JSON{start_line, end_line, replacement}`, span-windowed.
- Policy π: single structured-output LLM call.
- Transition: deterministic (apply edit, re-invoke V).

Why `diag_id` is the causal factor:
1. Classification is free — saves tokens baselines burn on stderr parsing.
2. Dead-end detection is a one-line rule because `diag_id` is categorical.
3. Cross-turn reasoning becomes discrete (`err_expected_semi → err_undeclared_var`).
4. Verifier selection reduces to `status == OK`.

### Integration Into Fuzzlang Infrastructure

- **Inference time**: harness feeds `(natural_buggy_src, compile_cmd)` from the NatErr split; DVCR calls only V.
- **Training-data time (for B2/B3 only)**: Fuzzlang Transformer mutates LLVM source offline; Fuzzlang Agent reproduces errors from `llvm-lit`. Both feed only B2/B3 SFT training, never the main eval split.

---

## NatErr Evaluation Pipeline

**Sources** (only commits on or after **2025-06-01**):

- **S1 — Git-history fault harvest**: fixed project list **{LLVM, Chromium, FFmpeg, LibreOffice, PostgreSQL, Blender, Qt, Bitcoin Core}**. Walk commits; flag *fix-build* commits (commit-message regex `/fix.*build|fix.*compil|unbreak.*build/i` or CI-red parent signal); check out the predecessor commit; attempt build under the project's declared CI config; if compile fails, record `(project, commit_sha, source_file, line, diag_id, compile_cmd)`.
- **S2 — Public CI failure logs**: scrape GitHub Actions / Buildbot for the same project set; filter to compile-error failures post 2024-10-01.
- **S3 — `llvm-lit` curated tests**: **excluded** from main eval (curated test-suite errors are not natural production errors). Used only for B2/B3 training.

**Filters**:
- Error severity = `error` (not warning-as-error).
- Reproducible under a publicly documented compile command.
- Commit SHA ≥ **2025-06-01** (safely beyond any plausible Qwen2.5-Coder training cutoff; 10+ months of data available through 2026-04-23).
- Not authored by any co-author of this paper.

**Dedup** (train ↔ eval):
- AST-hash dedup on a 5-line window around the error span against any Fuzzlang-LLVM training instance.
- `(diag_id, normalized_source_snippet)` dedup within the eval split itself.
- Project-level disjointness for the HPC appendix slice.

**Target size**: 3000 main + 500 HPC (appendix).

**Scope decision tree** (locked; no synthetic padding):

| Naturals collected | Action |
|---|---|
| ≥ 3000 | Proceed with full-scope Claim 1. |
| 1000 – 2999 | Proceed; explicitly label "Diagnostic-Verified Code Repair at 1k Scale". |
| 300 – 999 | Narrow Claim 1 to a single project (e.g., LLVM self-hosting) — depth study. |
| < 300 | Halt submission; escalate to author; never pad with synthetic. |

**Audit artifact**: a per-instance manifest `(project, commit_sha, source_file, line, diag_id, compile_cmd_hash)` released with the paper.

---

## Validation

### Claim 1 — MAIN (one table, four rows)

| Method | verified_fix_rate@T=5 | tokens | Description |
|---|---|---|---|
| B0 zero-shot | — | matched | No loop, no SFT. |
| B1 stderr-loop | — | matched | Self-Debug-style iterative, stderr text only. |
| B2 static SFT | — | matched | LoRA-SFT on Fuzzlang-LLVM + single-shot. |
| **DVCR (ours)** | — | matched | Loop + typed diag-ID + JSON edits. |

- All on the NatErr main split.
- Metric: `verified_fix_rate@T=5` — compiler-verified success under the original compile command with no new regressions, within budget T = 5 turns.
- 95% bootstrap confidence intervals.

### Causal Ablations — MAIN (three-way verifier-signal + one loop-off)

| Ablation | Observation | Isolates |
|---|---|---|
| DVCR (full) | `{diag_id, diag_name, diag_msg, span}` | — |
| **DVCR − id** | `{diag_name, diag_msg, span}` | Typed ID on top of structure |
| **DVCR − structure** | raw stderr | Structured interface in general |
| **DVCR − loop** | full observation, T = 1 | Loop |

Gradients:
- `DVCR − id` vs `DVCR − structure` → *structure alone*.
- `DVCR` vs `DVCR − id` → *typed categorical ID* on top of structure.

### Contamination Floor

Base-model `verified_fix_rate` on the NatErr main split, reported **pre-intervention**. Independent of any training-cutoff claim. All intervention deltas are reported relative to this floor.

### Appendix

- `B3 = SFT + stderr-loop` — pre-run, ready to surface if reviewers treat as the obvious stronger baseline.
- Notes / macro-expansion / template-chain inclusion variant.
- Trajectory trim {1, 2, full}.
- GCC cross-compiler transfer (one mini-table).
- Qwen2.5-Coder-**32B** scale robustness (the heavier model, run as appendix if compute permits).
- DTFT sanity check (LoRA-SFT on DVCR successful-rollout trajectories; one row).
- Budget sensitivity T ∈ {1, 2, 3, 5, 10}.
- Per-diagnostic-family breakdown.
- **HPC robustness** (OpenMP + OpenACC): DVCR vs B1 vs B2 on the HPC appendix slice (500 instances from HPC projects, zero Fuzzlang-Agent overlap).
- **Synthetic stress test**: run DVCR and baselines on Fuzzlang-Transformer-generated errors to expose the gap between natural-error and synthetic-benchmark numbers.

---

## Compute & Timeline

**Compute (Polaris A100-40GB, `diomp`)**:
- Main sweep on Qwen2.5-Coder-7B (4 methods × NatErr main + 4 ablation cells, 3 seeds each): ~200 GPU-hours. Inference single-GPU; LoRA SFT for B2/B3 on 1-2 GPUs.
- HPC appendix slice: ~30 GPU-hours.
- Verifier CPU farm: ~500 core-hours per sweep.
- Appendix: +200-400 GPU-hours if all enabled (including Qwen2.5-Coder-32B scale-robustness which is the most expensive item, ~300 GPU-hrs on its own).

**Timeline (NeurIPS 2026 full-paper deadline, ~May 2026)**:

- **W1** — Implement DVCR scaffolding (~600 LoC): V wrapper with primary-diagnostic rule; JSON-schema-constrained agent; parallel-sampling + verifier-select loop; matched-budget harness. Implement NatErr pipeline (~300 LoC).
- **W2** — Run NatErr; apply scope decision tree; lock eval split; measure contamination floor.
- **W3** — Main table (4 rows) + 3-way verifier-signal ablation + loop-off.
- **W4** — Appendix experiments (HPC, B3, GCC, 7B, budget, DTFT, per-family, synthetic stress); draft skeleton.
- **W5** — Paper draft.
- **W6** — External review loop (`/auto-review-loop`) + revision.
- **+1 week slack** before deadline.

---

## Handoff Inputs for `/experiment-plan`

**Must-prove**:
1. DVCR > B1 at matched budget on NatErr main.
2. DVCR > B2 at matched budget.
3. DVCR > DVCR − id at matched budget (typed-ID causal claim).

**Must-run**:
- Main 4-row table + 3-way verifier-signal ablation + loop-off.
- Contamination-floor measurement.
- NatErr manifest + audit-artifact release.

**Critical**: no LLM-as-judge anywhere; verifier is the only oracle; matched token budget; primary-diagnostic-only observation; naturals only in main table.

**Highest risks**:
1. Qwen2.5-Coder cutoff undocumented → contamination-floor measurement is the ground truth, independent of cutoff claim.
2. NatErr yield < 3000 → scope decision tree (narrow, do not pad).
3. DVCR ≈ DVCR − id → honest report; thesis weakens to *"structured inference-time compiler verifier"*; anchor still solved; paper still publishable.
