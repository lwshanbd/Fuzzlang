# Round 2 Refinement

## Problem Anchor (verbatim, unchanged)
[see `PROBLEM_ANCHOR.md` — anchored to: compiler diag output is the cheapest, most precise repair signal; no LLM pipeline closes the loop on it; reported gains collapse under rigorous isolation + compiler-oracle eval. Non-goals, constraints, success condition unchanged.]

## Anchor Check
- Bottleneck: unchanged.
- Does revised method still address it? Yes. All changes are mechanism-specificity tightening, no scope creep.
- Reviewer suggestions rejected as drift: none.

## Simplicity Check
- Dominant contribution: unchanged — DVCR inference-time agent with typed diag_id observation.
- Components removed/merged: trajectory input trimmed to last 2 pairs; multi-diag handling collapsed to "primary diagnostic only" rule; notes/macro/template traces dropped from main observation. Main table remains 4 rows.
- Reviewer suggestions rejected as unnecessary complexity: none — every suggestion tightens the existing mechanism.
- Why remaining mechanism is still smallest adequate: the only thing added is a more careful observation rule, a precise span_hash, and one more ablation cell (structured-no-id). No new component, no new trainable part.

## Changes Made

### 1. Three-way verifier-signal ablation (causal isolation)
- **Reviewer said**: R2 Item 1 — current `diag_id → stderr` swap confounds "typed categorical signal" with "better structured interface".
- **Action**: replace the single 2-way ablation with a **3-way verifier-signal ablation**:
  - `DVCR` (full): observation = `{diag_id, diag_name, diag_msg, span}`.
  - `DVCR − id` (structure, no ID): observation = `{diag_name, diag_msg, span}`. Preserves structured interface; removes only the integer ID.
  - `DVCR − structure` (stderr only): observation = raw compiler stderr text.
- **Impact**: cleanly isolates the typed-categorical-ID signal as the causal factor. DVCR − id vs DVCR − structure quantifies "structure alone"; DVCR vs DVCR − id quantifies "ID on top of structure".

### 2. Canonical multi-diagnostic observation rule
- **Reviewer said**: R2 Item 2 — missing integration point for multi-error/notes/macro-expansion/template-instantiation output.
- **Action**: **primary-diagnostic-only rule** for the main method:
  - Observation extracted from the **first `error:` record** in the compile output, taking its `(diag_id, diag_name, diag_msg, file, line, col, span)`.
  - Attached `note:` records, macro-expansion traces, and template-instantiation backtraces are **dropped** in the main method.
  - If fixing the primary diagnostic causes a different primary diagnostic to surface on re-compile, that is handled by the outer loop — no special logic.
  - Appendix ablation: include-notes variant.
- **Impact**: deterministic, defensible, avoids letting auxiliary compiler chatter turn into a second mechanism.

### 3. Precise `span_hash` definition
- **Reviewer said**: R2 Item 3 — need deterministic definition across compiler notes and rewritten code.
- **Action**:
  ```
  span_hash = sha256(
      diag_id || "|"
      || normalized_file_path || "|"
      || start_byte_offset || "|"
      || end_byte_offset || "|"
      || whitespace_normalized(source_snippet_at_span)
  )
  ```
  - `normalized_file_path` = path relative to project root.
  - `start_byte_offset`/`end_byte_offset` from Clang source-manager after macro expansion.
  - `whitespace_normalized` = collapse runs of whitespace, trim.
  - AST-normalized snippet intentionally **not** used (too fragile to invalid syntax in error states). Byte-level + whitespace-normalized is strict but reproducible.
- **Impact**: deterministic dead-end detection across branches.

### 4. Contamination-cutoff wording corrected
- **Reviewer said**: R2 Item 4 — weaken from "post-training-cutoff" unless documentable.
- **Action**: replace "post-cutoff" language with two separable claims:
  - Claim A (structural): evaluation-split commits drawn from LLVM after **2024-10-01** (a fixed, citable calendar date).
  - Claim B (measured): the **contamination floor** = base-model verified_fix_rate on the held-out split, reported regardless of whether the model has actually seen the commits. Interpret intervention gain relative to this floor, not relative to an asserted cutoff.
- **Impact**: robust even if Qwen2.5-Coder's cutoff is undocumented. The floor measurement does the work; the calendar cut is an additional precaution.

### 5. Trajectory trim + SFT + stderr-loop appendix-ready
- **Reviewer said**: Simplification #2 + Action Item 5.
- **Action**:
  - Trajectory input to `π` = last 2 `(diag_id, edit_summary)` pairs (not the full history). Ablation in appendix: trim to 1 vs full.
  - Add **B3 = SFT + stderr-loop** to the appendix baseline table, pre-run and ready to surface if reviewers at NeurIPS treat it as the obvious stronger baseline. Not in main table (keep it at 4 rows), but published alongside.
- **Impact**: trims input cost; defensive-ready for adversarial reviewers.

### 6. HPC slice reported with fallback
- **Reviewer said**: Simplification #1 — if HPC slice noisy / underpowered, remove from main table.
- **Action**: protocol: in W3 after running the main split, check OpenMP/OpenACC sample size × effect-size; if bootstrap CI on HPC column overlaps B1 by more than 50%, **demote the HPC column to appendix** and paper stands on Claim 1. No attempt to salvage with extra HPC runs under deadline pressure.
- **Impact**: removes the "HPC-column-or-bust" pressure; keeps Claim 1 bulletproof regardless.

## Revised Proposal (full)

### Title
**Diagnostic-Verified Code Repair: Typed Compiler Diagnostics as an Inference-Time Verifier for LLM Repair**

### Headline (locked)
*Typed compiler diagnostics used as an inference-time verifier signal produce measurably better compilation-error repair than stderr-text feedback and than static supervised fine-tuning, under project-level-isolated evaluation and at matched inference budgets, on C/C++ and directive-parallel (OpenMP/OpenACC) code.*

### Problem Anchor
[verbatim; unchanged]

### Technical Gap
Three failure modes unchanged. Intervention unchanged: put diag_id in the inference loop as a typed verifier observation.

### Contribution Focus
- **Dominant**: DVCR — inference-time agent with 488-class typed diag_id as a first-class observation.
- **Explicit non-contributions**: Fuzzlang-LLVM dataset, fine-tuning recipes, evaluation-protocol methodology, multi-compiler/multi-scale/multi-search policy.

### Proposed Method

#### Complexity Budget
**Frozen / reused**: modified Clang (diag-ID emission); modified `diagtool`; Fuzzlang Transformer (offline for B2 training data); Fuzzlang Agent pipeline (offline for held-in eval curation); Qwen2.5-Coder-32B-Instruct.

**New (inference-side only)**:
1. **Verifier V**: subprocess shim around modified Clang. In `(code, compile_cmd)`. Out `{status, diag_id, diag_name, diag_msg, file, line, col, span}`. Uses **primary-diagnostic-only rule**: read the first `error:` record, drop attached notes/macro-expansion/template-instantiation chains. Cached by `(code_hash, cmd_hash)`. ~250 LoC.
2. **Agent π**: one LLM call per turn per branch. Structured prompt fields: span-windowed snippet, `diag_id`, `diag_name`, `diag_msg`, **last 2 turns of trajectory** `[(diag_id_i, edit_summary_i)]`. Output constrained via JSON schema `{start_line: int, end_line: int, replacement: str}`. Rejected if schema-invalid or outside window `[max(0, diag.line − L), diag.line + L]` with L=5. ~400 LoC.
3. **Search**: parallel K=4 proposals at temp 0.8 per turn; verifier picks first OK with shortest-edit tiebreak; else advance all branches. Budget T=5.
4. **Terminal**: `status == OK` at original cmd AND whole-file re-compile has no new errors. Trivial-deletion guard: reject edits that delete non-trivial lines without replacement.
5. **Dead-end detection**: `span_hash = sha256(diag_id || "|" || normalized_file_path || "|" || start_byte_offset || "|" || end_byte_offset || "|" || whitespace_normalized(snippet))`. Same `span_hash` on two consecutive turns of a branch → kill branch, respawn from parent at temp 1.0. All K branches dead-end on same `span_hash` after T turns → FAIL.

#### Core Mechanism
- State `s_t = (src_t, diag_id_t, diag_name_t, diag_msg_t, span_t, traj_{<t}[-2:])`.
- Action `e_t = JSON{start_line, end_line, replacement}`, span-windowed.
- Policy π: single structured-output LLM call.
- Transition deterministic (apply edit, re-invoke V).

### Integration Into Fuzzlang Infra (unchanged)

### Validation

#### Claim 1 (MAIN, one table)

| Method | verified_fix_rate@T=5 | tokens | Notes |
|---|---|---|---|
| B0 zero-shot | — | matched | No loop, no SFT. |
| B1 stderr-loop | — | matched | Self-Debug style. |
| B2 static SFT | — | matched | LoRA-SFT on Fuzzlang-LLVM + single-shot. |
| DVCR (ours) | — | matched | Loop + typed diag-ID + JSON edits. |

Metric: `verified_fix_rate@T=5` (compiler-verified OK + no regressions), 95% bootstrap CI.

#### Causal Ablations (Main, 3-way + 1 loop-off)

| Ablation | Observation | Isolates |
|---|---|---|
| DVCR (full) | `{diag_id, diag_name, diag_msg, span}` | — |
| **DVCR − id** | `{diag_name, diag_msg, span}` | Typed ID on top of structure. |
| **DVCR − structure** | raw stderr text | Structured interface in general. |
| **DVCR − loop** | full observation, T=1 | Inference-time loop. |

The three-way sweep gives two clean gradients:
- `DVCR − id` vs `DVCR − structure` = "structure alone" effect.
- `DVCR` vs `DVCR − id` = **typed categorical ID** effect, independent of structure.

#### Claim 2 (SUPPORTING, one column on main table, with demote-to-appendix fallback)
OpenMP+OpenACC slice (~500 real ECP/Argonne-application errors, curated W2, zero Fuzzlang-Agent overlap). Fallback rule: if bootstrap CI overlaps B1 by >50%, move to appendix and drop Claim 2.

#### Data Isolation Protocol
- Evaluation-split commits from LLVM after **2024-10-01** (calendar cut).
- Project-level holdout for HPC.
- AST-hash dedup: no test instance shares normalized AST hash with any train instance.
- Diagnostic-family stratified.
- **Contamination floor** = pre-intervention base-model verified_fix_rate on the held-out split. Reported regardless of base-model training cutoff documentation. All intervention deltas reported relative to this floor.

#### Appendix-only
- `B3 = SFT + stderr-loop` (pre-run, ready to surface).
- Notes/macro-expansion/template-chain inclusion variant.
- Trajectory trim 1 vs 2 vs full.
- GCC cross-compiler transfer.
- Qwen2.5-Coder-7B scale robustness.
- DTFT (LoRA-SFT on DVCR trajectories) sanity check, single row.
- T ∈ {1,2,3,5,10} budget sweep.
- Per-diagnostic-family breakdown.

### Compute & Timeline

Polaris A100-40GB. Main sweep 4 methods + 4 ablation cells ≈ ~500 GPU-hrs on 32B. HPC slice ≈ 50 GPU-hrs. Verifier CPU farm ≈ 500 core-hours. Appendix experiments ≈ 200-400 GPU-hrs if all enabled.

Weeks:
- **W1** Scaffolding: V wrapper with primary-diagnostic-only rule; JSON-schema-constrained agent; parallel-sampling + verifier-select loop; matched-budget harness (~600 LoC).
- **W2** Splits: post-2024-10-01 LLVM + HPC curation + AST-hash dedup + contamination floor measurement.
- **W3** Main table (4 rows) + main ablation sweep (DVCR, −id, −structure, −loop). HPC column preliminary; demote-or-keep decision at end of W3.
- **W4** Final HPC column (if kept), contamination audit, appendix experiments (pre-run B3, etc.), draft skeleton.
- **W5** Paper draft + appendix consolidation.
- **W6** External review loop + revision.
- **+1 wk slack**.

### Handoff Inputs
**Must-prove**:
1. DVCR > B1 at matched budget on project-level-isolated split.
2. DVCR > B2 at matched budget.
3. DVCR > DVCR−id at matched budget (the typed-ID causal claim).
4. DVCR−id > DVCR−structure at matched budget (the structured-interface claim) — already a useful supporting fact but not required if (3) holds.

**Must-run**: 4-row main table + 3-way verifier-signal ablation + loop-off ablation + HPC column (or appendix) + contamination floor.

**Critical**: zero LLM-as-judge; verifier is the only oracle; matched token budget; primary-diagnostic-only observation rule.

**Highest risks**:
1. Qwen2.5-Coder cutoff undocumented. **Mitigation**: contamination-floor measurement supplies the ground truth independent of cutoff claims.
2. Post-2024-10-01 LLVM commits produce too few natural compile errors. **Mitigation**: if < 3k instances, supplement with Fuzzlang-Transformer-generated errors on post-cutoff commits, clearly labeled as such.
3. HPC curation underpowered. **Mitigation**: demote-to-appendix fallback rule.
4. `DVCR − id` matches `DVCR` closely → typed-ID claim collapses. **Mitigation**: this is the genuine scientific risk; the paper's honest version reports it and the contribution becomes "structured inference-time compiler verifier" rather than "typed categorical ID". Anchor still solved; thesis one step weaker.
