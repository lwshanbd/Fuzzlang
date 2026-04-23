# Research Proposal: Fuzzlang v2 — Closing the Compiler Loop for Diagnostic-Verified LLM Code Repair

> Working title. Final paper title will be decided after method freeze. For NeurIPS 2026, expected tracks: Datasets & Benchmarks (if the compiler-verifier benchmark angle dominates) or main track (if the agent-method angle dominates). Current plan favors the main track.

---

## Problem Anchor (verbatim from `PROBLEM_ANCHOR.md`)

### Bottom-line problem
LLM-based code repair for **compilation errors emitted by production C/C++/directive-parallel compilers** is still unreliable at the level demanded by real build systems. A model that scores well on synthetic benchmarks still fails on real errors from real projects, and "fine-tune a bigger dataset" has reached a clear diminishing-returns point once data isolation is enforced. The compiler itself — which produces the error and can verify any proposed fix for free — is treated as a passive data source rather than an active, loop-closing signal.

### Must-solve bottleneck
The compiler's own **diagnostic output (diagnostic ID + message + location)** is the cheapest, most precise ground-truth signal in existence for code-repair correctness, but today's LLM repair pipelines do not close the loop on it. Fine-tuned models are evaluated with LLM-as-judge or string-equivalence; agent repair ignores the structured diagnostic ID; reported gains collapse once data isolation is enforced and eval uses the compiler as oracle.

### Non-goals
- General-purpose coding agent competing on SWE-bench.
- Runtime / semantic bug fixing via test execution.
- New LLM architecture or new pre-training objective.
- Yet another synthetic error dataset as the main contribution.

### Constraints
- Venue NeurIPS 2026. Compute Polaris @ Argonne, project `diomp`. Open-weights preferred.
- Must leverage existing Fuzzlang assets (modified Clang with diagnostic-ID emission, modified `diagtool`, 660k-error Fuzzlang-LLVM corpus, Fuzzlang Transformer wrapper, Fuzzlang Agent).
- Hard methodology rules: project-level data isolation, no sibling-LLM judge, mandatory ablations, mandatory baselines, contamination audit.

### Success condition
Reviewers accept that (1) diagnostic-ID-grounded inference-time repair beats static fine-tuning and generic test-feedback agents; (2) the gain survives rigorous data isolation; (3) the method enables practically useful repair on HPC directive-based code where general methods fail.

---

## Technical Gap

**Current pipeline failure point**. Existing LLM code-repair pipelines fall into three buckets, and each has a specific failure mode for compilation errors.

1. **Static SFT pipelines** (Fuzzlang v1, OpenCodeInterpreter, HPC-Coder-v2): collect (buggy, error, fixed) triples, SFT an LLM, evaluate with LLM-as-judge. **Failure**: accuracy collapses under rigorous data isolation because mutation-generated train/test pairs are structurally near-duplicate. The OOPSLA reviewers were correct — the 93.97% / 96.70% headline numbers are isolation-inflated.

2. **Execution-feedback agents** (Self-Debug, Reflexion, SWE-agent, Agentless, RLEF): close the loop with unit-test pass/fail or stderr text. **Failure mode**: the feedback signal is either (a) binary (pass/fail), which collapses the 488-dimensional diagnostic space into one bit, or (b) free-form stderr text, which requires the agent to re-parse at every step. Neither feedback signal tells the agent *which kind of error remains* in a standardized way, so the agent wastes turns rediscovering classification facts the compiler already computed.

3. **LLM compiler fuzzing** (Fuzz4All, WhiteFox, FuzzGPT): uses the compiler to find bugs in the compiler, not to repair user code. Orthogonal.

**Why naive fixes are insufficient.** "Bigger model", "more mutation data", "longer context", "more retrieval" — all have been tried and all fail under honest data isolation. The diagnostic-ID signal is simply not in the feedback loop of any current method.

**Smallest adequate intervention.** Put the diagnostic ID in the loop. Expose the compiler as a typed verifier V(code, cmd) → (diag_id ∈ {1..488} ∪ {SUCCESS}, message, location, span). Let an LLM agent condition on the *diagnostic trajectory* — i.e., the sequence of diagnostic IDs produced by successive edit attempts — rather than on raw stderr. This is a single, minimal mechanism change. No new model. No new training objective (as the main claim). Just: the verifier is now inside the inference loop and its output is structured.

**Core technical claim** (to defend against top-venue scrutiny). *Diagnostic-ID-grounded inference-time repair beats both (a) static SFT and (b) stderr-text iterative repair, under project-level-isolated evaluation on real-world C/C++ and OpenMP/OpenACC compilation errors, at matched inference budgets, using the same base LLM.*

**Required evidence.**
1. A held-out evaluation split where train and test do not share project, commit, or AST structure.
2. Head-to-head comparison at matched token budgets with stderr-text iterative and with static SFT.
3. Ablations isolating the diagnostic-ID structure as the cause of the gain.
4. Transfer to a second compiler (GCC) and/or a different language front (OpenMP/OpenACC) to show the method is not LLVM-specific.

**Frontier-native alternative**. Could frame the same idea as RL-from-compiler-feedback (RLVR with diagnostic ID as process reward), aligning with 2025-era verifier-grounded RL (OpenAI o1 / DeepSeek-R1 style). This remains optional: if inference-time compiler-verifier loops already win cleanly, we do not need RLVR to make the paper.

---

## Method Thesis

**One-sentence thesis**: *A compilation-error repair agent that treats the compiler's structured diagnostic ID as a typed, dense verifier signal at inference time — without any new training — outperforms state-of-the-art SFT repair and execution-feedback agents under rigorous data isolation, and is uniquely enabling for directive-based parallel (OpenMP/OpenACC) code where pretrained LLMs have thin exposure.*

**Why this is the smallest adequate intervention**. The gain comes from closing one missing loop: making the compiler's own 488-class diagnostic vocabulary a first-class feature of the agent's observation space. Everything else (base model, prompting style, edit granularity, search policy) stays within the existing SOTA toolkit. No new architecture, no new pre-training, no new dataset required as the main contribution.

**Why this is timely**. Verifier-grounded inference-time scaling (AlphaCodium, Large Language Monkeys, Archon) is a 2024-2025 zeitgeist, but those verifiers are unit tests. The compiler is a better verifier for a large subset of real developer tasks — faster, cheaper, more structured, no test suite required, and already deployed on every build system. Fuzzlang already has the production-grade infrastructure (modified Clang + diagtool) to expose this verifier; no one else does.

---

## Contribution Focus

**Dominant contribution**. The **Diagnostic-Verified Code Repair (DVCR) agent**: a minimal inference-time agent architecture in which the compiler's structured diagnostic ID is a first-class observation, enabling the policy LLM to condition on the *diagnostic trajectory* rather than on stderr strings or pass/fail. This is the paper's mechanism and novelty.

**Optional supporting contribution**. The **rigorous evaluation protocol** and accompanying benchmark split: project-level holdout + temporal holdout + AST-dedup + diagnostic-family stratification + GCC cross-compiler transfer + OpenMP/OpenACC held-out subset. This protocol is not glamorous but is the thing that makes the main claim credible, and is reusable. Could be positioned as a D&B-track submission if main track is a poor fit; otherwise, a secondary contribution.

**Explicit non-contributions**.
- Fuzzlang-LLVM dataset generation pipeline is **supporting infrastructure**, not a contribution. It already exists. We report it in the appendix.
- Fine-tuning recipes, if any, are ablation components, not contributions.
- New compiler-fuzzing methodology. Not claimed.
- New LLM. Not claimed.

---

## Proposed Method

### Complexity Budget

**Frozen / reused**:
- Modified Clang (diagnostic-ID emission) — unchanged from Fuzzlang v1.
- Modified `diagtool` (`find-diagnostic-name`) — unchanged.
- Fuzzlang Transformer wrapper — unchanged, used offline for data generation and for sanity checks.
- Base LLM — e.g., Qwen2.5-Coder-32B-Instruct or Llama-3.3-70B-Instruct, used zero-shot or LoRA-adapted. No from-scratch training.
- Fuzzlang Agent error-reproduction pipeline — used offline to construct the evaluation set from `llvm-lit`; not part of the inference-time method.

**New (small, inference-side only)**:
1. **Diagnostic Verifier wrapper**: a thin Python shim around modified Clang that, given `(code, compile_command)`, returns a structured object `{status, diag_id, diag_name, message, file, line, col, span_pre_token, span_post_token}`. ~200 LoC. Caches compile results. Runs under a subprocess sandbox with CPU timeout.
2. **Diagnostic-Aware Agent policy**: a single LLM invocation per turn, conditioned on (source snippet around span, current diag_id + diag_name, short diag_message, prior diag trajectory as a compact textual trace). Output: a localized edit (line-range replacement). ~400 LoC of scaffolding.
3. **Search policy**: one of {greedy, best-of-K at first step, beam-K over diag trajectories, majority-vote over K independent runs}. Selector parameterized by budget; no learning component.
4. **Terminal criterion**: SUCCESS iff the verifier returns `status == OK` at the same compile_command that produced the original error, **and** no new error elsewhere in the file. This blocks the "silently delete the broken line" trivial fix.

**Tempting additions intentionally excluded** (explicit, to resist contribution sprawl):
- Multi-file, repo-level navigation (SWE-agent style). Out of scope — kept to file-local for compilation errors.
- Separate classifier model for error type. Not needed — the compiler already emits it.
- Separate retriever. Not needed for the core claim. Could be a later ablation.
- A new fine-tune objective or RL algorithm. Moved to "optional supporting experiment", not the headline.
- Multi-language scope beyond C/C++ + directive-parallel. Keeps the domain tight.

### System Overview

```
                  ┌─────────────────────────────┐
 source file  ──▶ │    Modified Clang (V)       │ ── (diag_id, span, msg) ──┐
 compile_cmd  ──▶ │    via Fuzzlang wrapper     │                           │
                  └─────────────────────────────┘                           │
                                                                            ▼
                  ┌─────────────────────────────┐        ┌──────────────────────────────┐
                  │  Terminal: status == OK &   │◀────── │  Diagnostic-Aware LLM Agent  │
                  │  no new error               │        │  input: snippet, diag_id,    │
                  └─────────────────────────────┘        │         diag_trajectory      │
                           │ SUCCESS                     │  output: localized edit e_t  │
                           │                             └──────────────────────────────┘
                           ▼                                        │ edit e_t
                       verified fix                                 │
                                                                    ▼
                                                    (apply e_t to source, go to V)
                             ( budget = max turns × max width )
```

### Core Mechanism: Diagnostic-Trajectory-Conditioned Edit Policy

- **State**: `s_t = (src_t, diag_id_t, diag_name_t, diag_msg_t, span_t, traj_{<t})`
  where `traj_{<t} = [(diag_id_0, edit_desc_0), (diag_id_1, edit_desc_1), ...]`.
- **Action**: `e_t = (line_range, replacement_text)`.
- **Policy**: `π_θ(e_t | s_t)` = a single LLM call with a tight prompt template that injects `diag_name_t` and `diag_msg_t` as structured fields, not as free text. LLM returns a localized edit, which is applied verbatim.
- **Transition**: deterministic — apply edit, re-invoke verifier, yield new `diag_id_{t+1}` or SUCCESS.
- **Loop budget**: `T` turns × `K` parallel branches. Default `T=5, K=4`. Token budget matched across baselines.

**Why diagnostic ID changes the game** (the mechanism argument):
1. **Classification is free**. The LLM no longer burns tokens to parse stderr.
2. **Trajectory becomes discrete**. The agent sees "went from `err_expected_semi` to `err_undeclared_var`" rather than "it still doesn't compile, here's another 2KB of stderr". This discrete signal supports simple, reliable decisions like backtrack / widen span / switch strategy.
3. **Dead-ends are detectable**. If the same `diag_id` repeats 3 times, the agent declares a dead-end and backtracks. This is implementable in 5 lines *only because* the ID is structured.
4. **Transfer is natural**. The same 488-way vocabulary is stable across Clang versions and partially shared with GCC diagnostic categories, so a policy trained/prompted on one can be evaluated on another.

### Optional Supporting Component: Diagnostic-Trajectory Fine-Tuning (DTFT)

*Only included if Phase 2 reviewer pushes for a training-side contribution, and only if it measurably beats zero-shot.*

- **Data**: rollouts of the zero-shot agent on the training split, filtered to successful trajectories.
- **Objective**: LoRA-SFT on `(s_t, e_t)` pairs where the trajectory eventually succeeded. No RL, no reward model, no PPO — keeps the contribution simple.
- **Role in paper**: ablation / section, not headline. Proves the inference-time story does not depend on expensive training.

If DTFT does not beat zero-shot at matched inference budget, we cut it. The main claim must stand on inference alone.

### Modern Primitive Usage

- **Inference-time search with a verifier** (AlphaCodium / Brown et al. 2024 Monkeys lineage): *exactly* the right primitive for this mechanism. The compiler is a free, deterministic, per-call-ms-scale verifier. We do not invent inference-time search; we show it is uniquely effective when the verifier emits a typed diagnostic vocabulary.
- **Agent scaffolding with a structured action space**: localized line-range edits, not free-form patches — mirrors Agentless' finding that simple actions often beat ReAct-style agents.
- **LoRA-SFT (optional DTFT)**: standard PEFT, used only as ablation.
- **Not used, by design**:
  - Full RL (PPO/GRPO): would require reward shaping and adds training complexity. The whole point is that inference-time loop + typed verifier already suffices.
  - Retrieval augmentation: no retrieval baseline for this task has published strong numbers under rigorous isolation, and adding it muddles the mechanism story.

### Integration Into Fuzzlang Infrastructure

- **At evaluation time**: DVCR agent receives `(buggy_src, compile_cmd)` from the evaluation harness. The harness comes from the Fuzzlang Agent Error Reproduction pipeline, used *offline* to produce the held-out evaluation set. At inference, we call only the verifier (modified Clang via the Fuzzlang wrapper).
- **At training-data time** (only for optional DTFT): the Fuzzlang Transformer pipeline mutates LLVM source and captures diagnostic-ID-labelled trajectories *at training time*. These trajectories are filtered and used for LoRA-SFT. The Fuzzlang dataset is a training-side byproduct, not the contribution.

### Training Plan (only for optional DTFT ablation)

- **Backbone**: Qwen2.5-Coder-7B (for fast iteration) and Qwen2.5-Coder-32B (for the main ablation point). Optionally Llama-3.1-8B for direct comparison to Fuzzlang v1 numbers.
- **Stage**: LoRA (rank 16) on filtered successful rollouts. 1 epoch, AdamW, bs 8, lr 2e-4, mixed precision bf16.
- **Data scale**: ~50k filtered trajectories from held-in LLVM commits only. No post-cutoff data.
- **Compute**: ~50 A100-hours per training run on 4×A100-40GB on Polaris.

### Failure Modes and Diagnostics

| Failure mode | Detection | Mitigation |
|---|---|---|
| Agent silently deletes broken lines to satisfy compile | Post-fix AST diff check: require at least one non-deleted non-whitespace edit on the span | Reject trivial-deletion fixes in the terminal criterion |
| Agent introduces a *different* error elsewhere to hide the original | Re-run full-file compile; SUCCESS requires no regressions | Already baked into terminal criterion |
| Diagnostic-ID distribution on test set is dominated by a few head classes → headline number misleading | Always report per-diagnostic-family accuracy, not just macro | Stratified eval and per-family tables |
| Agent memorizes training-set commits via base-model contamination | Use temporal holdout (train ≤ cutoff, test > cutoff) and report the base-model's pre-fine-tune hit rate on the test split as a contamination floor | Plot contamination-floor ↔ post-intervention accuracy |
| OpenMP/OpenACC numbers inflated by Fuzzlang Agent having generated them → near-duplicates | HPC eval set drawn from real ECP/Argonne applications, not from Fuzzlang Agent reproductions | Dedicated held-out HPC benchmark |
| Cross-compiler transfer fails (works on Clang, breaks on GCC) | Run GCC transfer as a mandatory ablation | Report honestly; transfer failure is a bounded-claim scenario, not a project-killer |

### Novelty and Elegance Argument

**Closest existing work**: RLEF (Meta 2024) uses RL from execution feedback on competitive programming. Exact differences:
1. Verifier type: execution pass/fail vs. compiler diagnostic ID (488-class vs. binary).
2. Paradigm: RL fine-tuning vs. pure inference-time loop.
3. Domain: competitive programming vs. production C/C++ and directive-parallel.

**Closest on agent side**: Agentless 2024. Differences:
1. Feedback used: tests vs. diagnostics.
2. Target: repo-level bugs vs. compilation errors.
3. Action granularity: patch vs. typed line-range edit.

**Closest on compiler side**: Fuzz4All, WhiteFox. Orthogonal direction — they use the compiler as fuzz target, we use it as repair verifier.

**Why it is a focused mechanism-level contribution** (not a module pile-up): the paper has exactly one headline mechanism, one supporting methodology (evaluation protocol), and zero new models or datasets being claimed as novel. Every other component is either reused or cut.

---

## Claim-Driven Validation Sketch

### Claim 1 (MAIN, mechanism-level).
*At matched inference budget and matched base model, a diagnostic-ID-conditioned inference-time agent (DVCR) outperforms (a) open-loop single-shot repair, (b) Self-Debug-style stderr-text iterative repair, and (c) static-SFT repair on a project-level-isolated compilation-error benchmark.*

- **Minimal experiment**: Single held-out evaluation split of compilation errors (≥ 3k instances) from LLVM commits past the base model's training cutoff + GCC cross-compiler subset + OpenMP/OpenACC subset (non-overlapping with Fuzzlang-LLVM training distribution).
- **Baselines** (critical — matched budget = matched output tokens):
  - B0: Zero-shot single-shot (no loop).
  - B1: Self-Debug-style (loop with stderr text, not diag ID).
  - B2: Static SFT on Fuzzlang-LLVM (= Fuzzlang v1 recipe), single-shot.
  - B3: SFT + loop with stderr text.
  - DVCR: our method (loop + diagnostic ID).
- **Metrics**:
  - `verified_fix_rate@T=5`: fraction of instances where the compiler returns OK under the original compile command with no new regressions, within budget T.
  - `token_efficiency`: verified_fix_rate / total output tokens.
  - `per-diagnostic-family breakdown`: macro average + per-family table to guard against head-class domination.
- **Expected evidence**: DVCR > B1 > B3 > B2 > B0 on the isolated split, with the DVCR ↔ B1 gap being the headline. If DVCR only marginally beats B1, the thesis weakens and we rethink.

### Claim 2 (SUPPORTING, domain-level).
*On HPC directive-based parallel code (OpenMP + OpenACC), where pretrained LLMs have thin exposure and base-rate repair is poor, DVCR enables practically useful repair quality otherwise unreachable; specifically, DVCR closes > 50% of the base-rate gap to the in-domain ceiling on a held-out HPC benchmark.*

- **Minimal experiment**: Curated OpenMP/OpenACC compilation-error benchmark drawn from real ECP applications + a subset of ParEval-style HPC tasks. Must not overlap with Fuzzlang Agent-reproduced training data.
- **Baselines**: same as Claim 1.
- **Metric**: `verified_fix_rate@T=5`, segmented OpenMP vs OpenACC.
- **Expected evidence**: base-rate is < 30% on OpenMP for all baselines; DVCR lifts it meaningfully (target > 60%). If it does not lift, the domain claim is dropped and the paper rests on Claim 1 alone.

### Mandatory Ablations
1. **Remove diagnostic-ID structure** → loop sees only stderr text. Expected: performance drops to ~B1 level. Demonstrates the ID is the causal factor.
2. **Remove loop** → single-shot only. Recovers B0.
3. **Remove budget** → T=1, recovers single-shot.
4. **Swap base model**: 7B vs 32B vs 70B at fixed DVCR config.
5. **Swap verifier signal type**: pass/fail binary vs stderr text vs diag_id. This is the decisive mechanism ablation.
6. **Data-isolation stress test**: intentionally leak training mutations into test → show reported metric inflates by X pp. Quantifies the OOPSLA issue.
7. **Cross-compiler transfer**: train/tune on Clang diagnostics, evaluate on GCC diagnostics with a diag-ID crosswalk table.
8. **Optional DTFT on/off**: at matched inference budget, show DTFT does not explain the gain.

### Contamination Audit
- Report base-model's verified_fix_rate on held-out test split *before* any intervention. This is the contamination floor.
- Use temporal holdout (LLVM commits > base-model training cutoff).
- AST-hash dedup between Fuzzlang-LLVM training distribution and evaluation split.
- Report diagnostic-family-stratified accuracy to detect head-class inflation.

---

## Experiment Handoff Inputs

**Must-prove claims**:
1. DVCR > stderr-text loop at matched budget on project-level-isolated split. (Claim 1, headline.)
2. DVCR > static SFT at matched budget. (Claim 1, vs Fuzzlang v1 recipe.)
3. Mechanism ablation: swapping diag-ID for stderr-text collapses the gain. (Causal evidence.)
4. HPC domain: DVCR lifts OpenMP/OpenACC repair above base rate. (Claim 2, optional but valuable.)

**Must-run ablations**:
- Verifier-signal swap, loop-off, budget-matched.
- Cross-compiler (Clang → GCC) transfer.
- Data-isolation stress test (intentional leakage).
- Base-model scale sweep (7B → 32B → 70B).

**Critical datasets / metrics**:
- Held-out: post-cutoff LLVM commits, HPC apps, ParEval-style, GCC transfer subset.
- Metric: `verified_fix_rate@T`, per-diagnostic-family.
- No LLM-as-judge anywhere.

**Highest-risk assumptions**:
1. Diagnostic IDs are stable enough across Clang versions used in training vs evaluation. (Mitigation: version-pin; report sensitivity.)
2. Post-cutoff LLVM commits produce non-trivial compilation errors. (Mitigation: pre-scan; fall back to mutation-generated held-out if needed.)
3. Base LLMs retain contamination-floor low enough to show intervention effect. (Mitigation: choose open models with documented cutoffs, e.g., Qwen2.5-Coder.)
4. OpenMP/OpenACC HPC benchmark can be curated in ≤ 2 weeks. (Mitigation: seed from existing ECP/ORNL benchmarks + user's own directive-based work [Shan et al. 2024].)

---

## Compute & Timeline Estimate

**Compute (Polaris, project `diomp`)**:
- Main inference sweep: DVCR + 4 baselines × 3 model scales × 5 budgets × held-out eval (~5k instances) ≈ 4–6k GPU-hours total (A100-40GB). Fits comfortably in a Polaris allocation with 1 week of wall time with modest parallelism (16 nodes).
- Optional LoRA DTFT ablation: ~100 GPU-hours per model.
- Modified-Clang compile-verifier farm: CPU-only, ~1k CPU-core-hours for the full held-out set per baseline sweep.

**Timeline (targeting NeurIPS 2026 full-paper deadline, ~May 2026)**:

- **Week 1 (now)**: Implement DVCR scaffolding (~600 LoC). Lock evaluation harness with modified Clang verifier.
- **Week 2**: Build contamination-rigorous eval splits (post-cutoff LLVM + HPC + GCC transfer + ParEval subset). Dedup against Fuzzlang-LLVM training distribution.
- **Week 3**: Main experiment sweep (Claim 1). All baselines at matched budgets.
- **Week 4**: Ablations + HPC experiments (Claim 2) + GCC transfer.
- **Week 5**: Paper draft. Optional DTFT ablation if time permits.
- **Week 6**: External review round (via `/auto-review-loop`) + rebuttal-ready revisions.

**Risk buffer**: 1 week slack before deadline. If Claim 2 collapses, reframe as Claim 1-only submission; do not attempt salvage experiments under deadline pressure.

---

*End of round-0 initial proposal. Next: Phase 2 review by Codex (gpt-5.4, xhigh) in `refine-logs/round-1-review.md`.*
