# Round 1 Refinement

## Problem Anchor (verbatim from `PROBLEM_ANCHOR.md`)

### Bottom-line problem
LLM-based code repair for compilation errors emitted by production C/C++/directive-parallel compilers is still unreliable at the level demanded by real build systems. A model that scores well on synthetic benchmarks still fails on real errors from real projects, and "fine-tune a bigger dataset" has reached a clear diminishing-returns point once data isolation is enforced. The compiler itself — which produces the error and can verify any proposed fix for free — is treated as a passive data source rather than an active, loop-closing signal.

### Must-solve bottleneck
The compiler's own diagnostic output (diagnostic ID + message + location) is the cheapest, most precise ground-truth signal in existence for code-repair correctness, but today's LLM repair pipelines do not close the loop on it.

### Non-goals
- General-purpose coding agent competing on SWE-bench.
- Runtime / semantic bug fixing.
- New LLM architecture or pre-training objective.
- Yet another synthetic error dataset as the main contribution.

### Constraints
- NeurIPS 2026. Polaris / `diomp`. Open-weights preferred. Reuse Fuzzlang v1 infra. Project-level isolation. No sibling-LLM judge. Mandatory ablations + baselines + contamination audit.

### Success condition
(1) diag-ID-grounded inference-time repair beats static SFT and stderr-feedback agents; (2) survives rigorous data isolation; (3) enables practical HPC directive-parallel repair.

---

## Anchor Check

- **Original bottleneck**: compiler's structured diagnostic signal is not in the inference-time loop of any LLM repair method.
- **Does the revised method still address it?** Yes. All deletions are secondary stories (multi-compiler transfer, multi-scale sweeps, optional fine-tune). The diagnostic-ID-in-the-loop mechanism is untouched and in fact sharper after pruning.
- **Reviewer suggestions rejected as drift**: none. All suggestions are subtraction, which strengthens anchor fidelity.

## Simplicity Check

- **Dominant contribution after revision**: typed diagnostic-aware inference-time repair (DVCR). Single mechanism-level claim.
- **Components removed or merged**:
  1. **DTFT** (Diagnostic-Trajectory Fine-Tuning) — deleted from main plan. Moved to a single one-row appendix robustness check: "does zero-shot DVCR's gain survive when we *also* fine-tune?" Not a claim; a sanity check.
  2. **GCC cross-compiler transfer** — deleted from main plan. Appendix-only robustness if time permits.
  3. **Multi-scale sweep** (7B / 32B / 70B) — reduced to single headline model: **Qwen2.5-Coder-32B-Instruct**. 7B only if 32B cannot run at budget; 70B not in main.
  4. **Multi-budget sweep** — reduced to a single default budget `T=5, K=4` for the main table. Budget sensitivity → appendix.
  5. **Multi-search-policy comparison** — deleted. One search policy: **parallel proposal sampling + exact verifier selection**, shortest-edit tiebreak. Beam / majority-vote / greedy all → appendix curiosity only if budget allows.
- **Reviewer suggestions rejected as unnecessary complexity**: none. All reviewer suggestions were about cutting, not adding.
- **Why the remaining mechanism is still the smallest adequate route**: one verifier call contract, one agent policy call per turn per branch, one search rule. Zero new trainable components in the main claim. Zero new datasets claimed as novel. One causal ablation plus one loop-off ablation prove the mechanism.

## Changes Made

### 1. Paper identity locked to one sentence
- **Reviewer said**: Venue Readiness (6) — paper still trying to be method + benchmark + protocol + optional-training at once.
- **Action**: Replaced the prior paragraph-long thesis with a single locked headline sentence, reused in abstract and conclusion verbatim.
- **New headline**: *"Typed compiler diagnostics used as an inference-time verifier signal produce measurably better compilation-error repair than stderr-text feedback and than static supervised fine-tuning, under project-level-isolated evaluation and at matched inference budgets, on C/C++ and directive-parallel (OpenMP/OpenACC) code."*
- **Impact**: paper identity now method-paper first, benchmark/protocol second, no third identity.

### 2. Main experiment table frozen at 4 rows + 2 ablations
- **Reviewer said**: Validation Focus (5) — matrix too large, blurs causality.
- **Action**: Main experiments = one table, 4 rows (B0 single-shot, B1 stderr-loop, B2 static SFT / Fuzzlang v1 recipe, DVCR); one matched budget; one base model; one isolated split. Main causal story = two ablations: (a) `diag_id → stderr` swap, (b) loop-off. Everything else appendix.
- **Impact**: a reviewer can point at one table and immediately see the DVCR↔B1 gap. Causal ablation (a) proves diag_id is the cause.

### 3. Edit action moved to constrained JSON tool-call schema
- **Reviewer said**: Modernization #1 — emit edits as constrained tool-call schema.
- **Action**: action space = JSON object `{start_line, end_line, replacement}`, enforced via LLM structured-output / JSON-schema constraint at generation time. Rejected if schema-invalid or outside span ± L lines (L=5 default). This tightens edit-localization (Method Specificity ↑).
- **Impact**: simpler parse, deterministic edit application, cleaner ablation against stderr-loop.

### 4. Search policy locked to "parallel sampling + verifier selection"
- **Reviewer said**: Modernization #2 — prefer parallel proposal sampling + exact verifier selection over beam scorer.
- **Action**: at each turn, K=4 parallel edit proposals at temperature 0.8; run verifier on all; if ≥1 yields SUCCESS, select shortest-edit; else advance every branch to next turn. Repeated-diagnostic-ID dead-end detection: if a branch's last 2 turns share `(diag_id, span_hash)`, kill branch and respawn from parent at temperature 1.0. If all K branches dead-end on same diag_id, terminate with FAIL.
- **Impact**: deterministic scoring (verifier), no learned scorer, no beam hyperparameter.

### 5. Method Specificity gaps (score 7) closed
- **Reviewer said**: edit-localization contract, branch scoring over trajectories, repeated-diagnostic backtracking underspecified.
- **Action**:
  - Edit localization contract: edits must intersect the span window `[max(0, diag.line − L), diag.line + L]` with L=5. Edits outside are rejected at the scaffold level (counted as no-op turns).
  - Branch scoring: SUCCESS detection replaces scoring; verifier is the scorer. No partial-credit scoring needed.
  - Repeated-diagnostic backtracking: as above — same `(diag_id, span_hash)` twice kills a branch.
- **Impact**: Method Specificity should now reach 9.

### 6. HPC slice scoped to one held-out subset
- **Reviewer said**: Feasibility (6) — HPC benchmark as separate track is overcommitted.
- **Action**: ONE held-out HPC slice = ~500 compilation errors from real ECP / Argonne applications using OpenMP+OpenACC directives, curated in week 2, non-overlapping with Fuzzlang Agent training data. Reported as a single column alongside the main table, not as a second main table.
- **Impact**: domain claim (Claim 2) kept but right-sized.

### 7. DTFT demoted to single appendix row (not main claim)
- **Reviewer said**: Simplification #1 — DTFT creates a second paper inside the first.
- **Action**: main claim is zero-training. DTFT runs only if schedule permits; appears as one extra row in appendix table, framed as "does SFT close remaining gap?", not "we propose DTFT". The paper's zero-training stance is the stance — DTFT is only a sanity check.
- **Note on pushback**: the user's original framing included "fine-tune + agent combination" as a direction. This is preserved as a single appendix row rather than as a headline, because making DTFT a co-equal contribution is exactly what the reviewer correctly flagged as dilution. If user explicitly wants DTFT back as a co-equal contribution we can escalate in Round 2; otherwise we keep it demoted.

### 8. GCC transfer demoted to appendix
- **Reviewer said**: Simplification #3 — Clang-only + one HPC slice is the full scope of the core paper.
- **Action**: GCC transfer → appendix, run only if time in Week 4 permits. Paper's main claim is Clang-scoped; transfer is a bounded-claim robustness check, not a headline.

---

## Revised Proposal

### Title (working)
**Diagnostic-Verified Code Repair: Typed Compiler Diagnostics as an Inference-Time Verifier for LLM Repair**

### Headline sentence (locked)
*Typed compiler diagnostics used as an inference-time verifier signal produce measurably better compilation-error repair than stderr-text feedback and than static supervised fine-tuning, under project-level-isolated evaluation and at matched inference budgets, on C/C++ and directive-parallel (OpenMP/OpenACC) code.*

### Problem Anchor
[identical, omitted — see top of this document]

### Technical Gap
1. **Static SFT pipelines** (Fuzzlang v1, OpenCodeInterpreter, HPC-Coder-v2): accuracy collapses under rigorous data isolation.
2. **Execution-feedback agents** (Self-Debug, Reflexion, SWE-agent, Agentless, RLEF): feedback is pass/fail or free-form stderr — collapses or ignores the 488-class diagnostic structure.
3. **LLM compiler fuzzing** (Fuzz4All, WhiteFox, FuzzGPT): orthogonal — uses compiler to find compiler bugs, not to repair user code.

Smallest adequate intervention: put the diag ID in the loop. Expose the compiler as a typed verifier `V(code, cmd) → {OK} ∪ {(diag_id ∈ [1..488], diag_name, msg, file, line, col, span)}`. Agent conditions on diagnostic trajectory, not stderr.

### Method Thesis (one sentence, see headline)

### Contribution Focus
- **Dominant contribution**: DVCR — inference-time agent that treats the compiler's 488-class diagnostic ID as a first-class typed observation.
- **Non-contributions (explicit)**: Fuzzlang-LLVM dataset (reused infrastructure), fine-tuning recipes (appendix sanity check), evaluation-protocol methodology (supporting rigor, not a second contribution), multi-compiler / multi-scale / multi-search-policy (appendix only).

### Proposed Method

#### Complexity Budget

**Frozen / reused**:
- Modified Clang (Fuzzlang v1 diag-ID emission).
- Modified `diagtool`.
- Fuzzlang Transformer wrapper (offline only, for Fuzzlang-LLVM data prep of the static-SFT baseline).
- Base LLM: **Qwen2.5-Coder-32B-Instruct**. No from-scratch training.
- Fuzzlang Agent pipeline (offline only, for held-in eval-split curation).

**New (inference-side only, minimal)**:
1. **Diagnostic Verifier wrapper V**: thin subprocess shim around modified Clang. Input `(code, compile_cmd)`. Output `{status, diag_id, diag_name, msg, file, line, col, span}`. Caches by (code_hash, cmd_hash). CPU timeout 10s. ~200 LoC.
2. **Diagnostic-Aware Agent policy π**: one LLM call per turn per branch. Structured prompt fields: source snippet around span, current `diag_id + diag_name`, `diag_msg`, compact trajectory `[(diag_id_0, edit_summary_0), …]`. Structured-output constraint: JSON `{start_line: int, end_line: int, replacement: str}`. Rejected if schema-invalid or outside span window (L=5 lines).
3. **Search**: parallel proposal sampling K=4 at temp 0.8 per turn; verifier selects first OK with shortest-edit tiebreak; else advance all branches to next turn. Budget T=5. Matched token budget for all baselines.
4. **Terminal criterion**: `status == OK` at the original compile command AND no new error elsewhere in the file (whole-file re-compile check). Trivial-deletion guard: reject edits that delete non-trivial lines without any replacement.
5. **Dead-end detection**: same `(diag_id, span_hash)` on two consecutive turns of a branch → kill branch + respawn from parent at temp 1.0. All K branches same diag_id after T turns → FAIL.

**Not used, by design**: multi-file navigation, error-type classifier (compiler emits), retriever, full RL, beam/majority-vote/greedy (parallel sampling + verifier is the single locked search policy), cross-compiler crosswalk (appendix).

#### System Overview

```
 (source, compile_cmd) ──▶  Verifier V (mod Clang)  ──▶ diag_id or OK
                                     │
                                     ▼
            ┌─────────── OK? ────────┐
            │                        │
           OK                     diag_id
        → verified                    │
          fix                         ▼
                           Agent π (K parallel edits)
                                     │
                                     ▼
                              apply edits, loop
```

Budget envelope: `T × K` verifier calls per instance; matched output-token envelope across all baselines.

#### Core Mechanism: Diagnostic-Trajectory-Conditioned Edit Policy

- State `s_t = (src_t, diag_id_t, diag_name_t, diag_msg_t, span_t, traj_{<t})`; `traj_{<t} = [(diag_id_i, edit_summary_i)]_{i<t}` compactly textualized.
- Action `e_t = JSON{start_line, end_line, replacement}` constrained to span ± L.
- Policy π: single LLM call, structured output enforced.
- Transition deterministic (apply edit, re-invoke V).

Why diag ID is the causal factor:
1. Classification is free (saves tokens the baselines burn on stderr parsing).
2. Dead-end detection is a 1-line rule *because* diag ID is categorical.
3. Cross-turn reasoning becomes discrete (`err_expected_semi → err_undeclared_var`), legible in context.
4. Verifier selection reduces to checking `status == OK`.

#### Integration Into Fuzzlang Infra

- **Eval-time**: harness feeds `(buggy_src, compile_cmd)` to DVCR. DVCR calls only V (modified Clang via Fuzzlang wrapper).
- **Eval-curation-time (offline)**: Fuzzlang Agent reproduces errors from `llvm-lit` tests to build the held-in split; Fuzzlang Transformer generates a mutation-based split for the static-SFT baseline B2. Held-out splits are constructed independently (see below).

### Validation

#### Claim 1 (MAIN, one table)
At matched base model (Qwen2.5-Coder-32B) and matched inference-token budget, on a project-level-isolated compilation-error split, DVCR beats B0/B1/B2 by a meaningful margin; the **DVCR vs B1 gap (stderr-text iterative)** is the headline delta.

**Main table (single)**:

| Method | verified_fix_rate@T=5 | tokens | Notes |
|---|---|---|---|
| B0 zero-shot single-shot | — | matched | No loop, no SFT. |
| B1 stderr-loop | — | matched | Self-Debug-style iterative, stderr text only. |
| B2 static SFT | — | matched | LoRA-SFT on Fuzzlang-LLVM + single-shot. |
| **DVCR (ours)** | — | matched | Loop + diag-ID + JSON edits. |

**Two decisive ablations**:

| Ablation | Question answered |
|---|---|
| DVCR − diag_id (use stderr text) | Isolates diag-ID as causal factor. |
| DVCR − loop (T=1) | Isolates loop contribution. |

Metric: `verified_fix_rate@T=5` = compiler-verified success (OK, no new errors) within 5 turns. Reported with 95% bootstrap CI. Per-diagnostic-family breakdown reported but in appendix unless it changes the conclusion.

#### Claim 2 (SUPPORTING, one column)
On a held-out OpenMP/OpenACC HPC slice (~500 errors from real ECP/Argonne apps, curated in W2, zero overlap with Fuzzlang Agent training data), DVCR lifts repair rate above stderr-loop and static-SFT baselines. Reported as one added column on the main table (OpenMP+OpenACC stratified), not as a separate main table.

If the HPC lift is not significant → drop Claim 2; paper stands on Claim 1.

#### Data Isolation Protocol (supporting rigor, one paragraph in method + one appendix)
- **Temporal holdout**: evaluation instances only from LLVM commits > Qwen2.5-Coder training cutoff (~Oct 2024).
- **Project-level holdout for HPC slice**: all test projects disjoint from any project used in Fuzzlang Agent training.
- **AST-hash dedup**: no test instance shares a normalized AST hash with any train instance.
- **Diagnostic-family stratified split**: test includes held-out diagnostic families.
- **Contamination floor**: report base-model verified_fix_rate on test split *before* any intervention as the floor.

#### Appendix-only, time-permitting
- GCC cross-compiler transfer (single mini-table).
- Base-model scale sensitivity (Qwen2.5-Coder 7B only, if 32B is already clean).
- DTFT sanity check (one row: DVCR + LoRA-SFT on held-in trajectories; must at least not hurt).
- Budget sensitivity T∈{1,2,3,5,10} for DVCR and B1.
- Per-diagnostic-family table.

### Compute & Timeline

**Compute (Polaris, `diomp`)**:
- Main sweep: 4 methods × ~5k eval instances × T=5 × K=4 (for DVCR) ≈ 400 GPU-hours on Qwen2.5-Coder-32B. Fits in a single allocation, 2 days wall at 4 nodes.
- HPC slice: ~500 instances × 4 methods × same budget ≈ 40 GPU-hours.
- Clang verifier farm: CPU-side, ~500 core-hours per sweep.
- Appendix experiments: +200-400 GPU-hours if all enabled.

**Timeline (NeurIPS 2026 May deadline)**:
- W1 DVCR scaffolding (~600 LoC) + V wrapper + JSON-schema edit enforcement + matched-budget harness.
- W2 Isolated eval split (post-cutoff LLVM + HPC curation + AST-dedup + contamination-floor measurement).
- W3 Main sweep (4-row table) + two ablations.
- W4 HPC slice column + contamination audit + paper draft skeleton.
- W5 Paper draft + appendix experiments if schedule permits.
- W6 External review loop (`/auto-review-loop`) + revision.
- 1-week slack.

### Handoff Inputs for `/experiment-plan`

**Must-prove**:
1. DVCR > B1 (stderr-loop) at matched budget on isolated split.
2. DVCR > B2 (static SFT) at matched budget.
3. Causal ablation: `diag_id → stderr` swap collapses gain.

**Must-run**:
- Two causal ablations only (loop-off, diag_id → stderr).
- Contamination-floor measurement.
- HPC column.

**Critical**: zero LLM-as-judge; verifier is the only oracle; matched token budget.

**Highest risks**:
1. Diag-ID stability across Clang version used for verifier vs held-out commits' compile commands. Mitigation: version-pin verifier; reject test instances whose original error differs under the pinned version.
2. Post-cutoff LLVM error availability. Mitigation: pre-scan; fall back to Fuzzlang-Transformer-generated held-out on post-cutoff commits if needed.
3. HPC curation timeline. Mitigation: seed from user's own directive-based prior work (Shan 2024); concurrent with W1.
