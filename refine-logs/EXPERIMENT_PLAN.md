# Experiment Plan

**Problem**: LLM-based code repair for compilation errors does not close the loop on the compiler's own structured diagnostic output; reported gains collapse under rigorous data isolation.
**Method Thesis**: Typed compiler diagnostics used as an inference-time verifier signal produce measurably better compilation-error repair than stderr-text feedback and than static supervised fine-tuning, under project-level-isolated evaluation and at matched inference budgets, on natural C/C++ compilation errors from real projects.
**Date**: 2026-04-23
**Venue**: NeurIPS 2026 main track
**Compute**: Polaris @ Argonne, project `diomp`, Qwen2.5-Coder-7B-Instruct headline + 32B appendix

---

## Claim Map

| ID | Claim | Why It Matters | Minimum Convincing Evidence | Linked Blocks |
|---|---|---|---|---|
| **C1** | **DVCR > B1 stderr-loop AND DVCR > B2 static SFT**, at matched base model (Qwen2.5-Coder-7B) and matched output-token budget, on NatErr natural-C/C++-errors split. | The paper's central mechanism claim. If this fails, the paper does not exist. | 4-row main table, 3 seeds, non-overlapping 95% bootstrap CIs between DVCR and the next-best row. Absolute gap ≥ 5 pp on `verified_fix_rate@T=5`. | B1 |
| **C2** | **DVCR > DVCR−id** at matched budget. | Isolates the typed 488-class ID as the causal factor on top of "structured feedback in general". Without this, the contribution degrades from "typed diagnostics" to "any structured compiler feedback". | 3-way signal ablation, 3 seeds, DVCR−id beats DVCR−structure (structure helps) AND DVCR beats DVCR−id (ID helps on top of structure). Each gap ≥ 3 pp with non-overlapping CI or p<0.05. | B2 |
| **C3** (supporting) | DVCR's lift persists on **HPC directive-parallel** (OpenMP + OpenACC) natural errors from real projects. | Domain robustness; reused Fuzzlang v1 infra is uniquely positioned here. Appendix-only result. | Appendix table, single column on HPC NatErr slice, DVCR > B1 with positive-direction gap. | B5 appendix |

### Anti-claims explicitly ruled out

| Anti-claim | Where it is ruled out |
|---|---|
| A1: "DVCR beats B1/B2 only because it uses more compute / longer token budget." | Matched-budget protocol: same max output-token envelope per instance across all methods. |
| A2: "DVCR beats B1 only because the JSON-schema interface is more structured, not because of diagnostic IDs." | Three-way ablation DVCR−id isolates structure from ID. |
| A3: "Gains are because B2 overfits to mutation-generated training and fails on naturals — any inference-time method would beat it." | B1 stderr-loop uses the same base model with no SFT and is a strong comparator; head-to-head DVCR vs B1 is the clean test. |
| A4: "The loop is what matters, not the diag_id signal." | Loop-off ablation (DVCR − loop, T=1) quantifies the loop contribution separately; combined with three-way signal ablation this isolates all three axes. |
| A5: "Results are contamination artifacts — Qwen2.5-Coder has seen these commits." | Calendar cutoff 2025-06-01 + measured contamination floor on the held-out split. All gains reported relative to the floor. |
| A6: "The numbers are inflated by LLM-as-judge." | Compiler is the only oracle. No LLM judge anywhere in the main table. |
| A7: "Gains are from head-class domination of a few diagnostic types." | Per-diagnostic-family breakdown reported in appendix; macro-average alongside micro-average in the main table. |
| A8: "DVCR works only because Clang is special (modified ID emission); it's a Clang trick, not a method." | GCC cross-compiler transfer in appendix probes whether the mechanism transfers under a diagnostic-ID crosswalk. |

---

## Paper Storyline

**Main paper must prove**:
- **C1** (main 4-row table) and **C2** (three-way signal ablation).
- Loop contribution isolated from signal contribution.
- Contamination floor reported so gains are honest.
- At least one qualitative / failure-mode section so reviewers can see where DVCR still loses.

**Appendix supports**:
- **C3** HPC domain robustness.
- Rigor: B3 SFT+stderr-loop "strongest plausible baseline" safety row; GCC transfer; Qwen2.5-Coder-32B scale robustness.
- Mechanism depth: notes / macro / template-chain inclusion variant; trajectory trim sensitivity; budget T sensitivity; DTFT sanity row; per-family table; synthetic stress test (Fuzzlang-Transformer errors — shows natural↔synthetic gap).

**Experiments intentionally cut**:
- Multi-search-policy comparison (greedy / beam / MCTS / majority-vote). Skill's R1 advice — do not turn the paper into a search-engineering paper.
- Multi-base-family (Llama / DeepSeek / StarCoder). One coder model is enough for C1/C2.
- Multi-language beyond C/C++ + directive-parallel. Out of anchor scope.
- Retrieval augmentation. No RAG baseline for compilation errors has published strong numbers under rigorous isolation; adding it muddles the mechanism story.
- Full RL (PPO / GRPO / DPO). The whole point is inference-time suffices.

---

## Experiment Blocks

### Block B1 — Main anchor result (MUST-RUN)

- **Claim tested**: C1 (and part of A1).
- **Why this block exists**: the paper's 4-row table. Without this, there is no paper.
- **Dataset / split / task**: NatErr main split. Natural compilation errors from commits ≥ 2025-06-01 in {LLVM, Chromium, FFmpeg, LibreOffice, PostgreSQL, Blender, Qt, Bitcoin Core}. Target n ≥ 3000 per scope decision tree; fallback tiers narrow scope.
- **Compared systems (4 rows, all Qwen2.5-Coder-7B-Instruct at matched output-token budget)**:
  - **B0** zero-shot single-shot: one LLM call with `(buggy_src, compile_cmd, stderr)` → full patched source.
  - **B1** stderr-loop: Self-Debug-style iterative, T=5 turns × K=4 branches, JSON-schema edit action same as DVCR, but observation = raw compiler stderr text (no structured fields).
  - **B2** static SFT: LoRA-rank-16-SFT on Fuzzlang-LLVM held-in mutations (Fuzzlang v1 recipe), then single-shot inference like B0.
  - **DVCR** (ours): T=5, K=4, observation = `{diag_id, diag_name, diag_msg, span}`, JSON-schema edit action, parallel-sampling + verifier selection, span-hash dead-end detection, primary-diagnostic-only rule.
- **Metrics**:
  - Primary: `verified_fix_rate@T=5` (compiler-verified OK under original compile_cmd, whole-file no-regression, trivial-deletion guard), 95% bootstrap CI, 3 seeds.
  - Secondary: `token_efficiency` = `verified_fix_rate / avg_output_tokens`.
  - Secondary: `avg_verifier_calls`, `avg_turns_to_success` (successes only).
  - Reported both micro-avg and macro-avg-over-diagnostic-family.
- **Setup details**:
  - Qwen2.5-Coder-7B-Instruct, FP16, vLLM.
  - Temp 0.8 for sampling K=4 proposals.
  - Matched token envelope per instance: `E_tokens = 5 (T) × 4 (K) × 256 (per-call cap) = 5120` output tokens per instance for loop methods; B0 / B2 get `E_tokens` in one shot.
  - B2 training: LoRA rank 16, 1 epoch, bs 8, lr 2e-4, bf16, ~50k filtered (buggy, error, fixed) triples from Fuzzlang-LLVM train split.
  - Seeds {17, 23, 42} for all stochastic sampling.
- **Success criterion**: DVCR's verified_fix_rate − B1's ≥ 5 pp AND their 95% CIs do not overlap. Same vs B2.
- **Failure interpretation**:
  - DVCR ≤ B1 → central thesis refuted; do NOT publish until Phase 3 (proposal revision) re-opened.
  - DVCR > B1 but < 5 pp → honest report; consider "small but significant structured-feedback gain" framing.
  - DVCR > B1 but ≤ B2 → B2's mutation-SFT generalized surprisingly well to naturals; investigate whether data-isolation was correctly enforced.
- **Table / figure target**: Table 1 (headline), Figure 1 (schematic of the 4 methods' observation/action flow).
- **Priority**: **MUST-RUN**.

### Block B2 — Novelty isolation: 3-way verifier-signal ablation (MUST-RUN)

- **Claim tested**: C2 (and A2, A8).
- **Why this block exists**: the paper's causal ablation. Without this, the "typed diagnostic ID" claim is a just-so story.
- **Dataset / split / task**: same NatErr main split as B1.
- **Compared systems (3 rows, all Qwen2.5-Coder-7B, loop T=5, K=4, matched token budget)**:
  - **DVCR** (full signal): observation = `{diag_id, diag_name, diag_msg, span}`.
  - **DVCR − id** (structured, no ID): observation = `{diag_name, diag_msg, span}`. Diagnostic text + span preserved; integer ID removed. This isolates ID from structure.
  - **DVCR − structure** (stderr only): observation = raw compiler stderr text. Same loop and action schema as DVCR; just the observation channel collapses to unstructured text.
- **Metrics**: same as B1. Reported at matched budget.
- **Setup details**: same seeds, same base model, same search policy. Only the observation field differs.
- **Success criterion**:
  - DVCR > DVCR − id ≥ 3 pp with non-overlapping CI → typed-ID claim supported.
  - DVCR − id > DVCR − structure ≥ 3 pp with non-overlapping CI → structured-interface claim also supported (stronger story).
- **Failure interpretation**:
  - DVCR ≈ DVCR − id → typed-ID claim collapses. Thesis weakens to "structured inference-time compiler verifier"; rewrite headline accordingly; anchor still solved. This is the pre-identified scientific risk.
  - DVCR − id ≈ DVCR − structure → structure alone does not help; implausible but would refute the entire mechanism framing.
- **Table / figure target**: Table 2 (causal ablation).
- **Priority**: **MUST-RUN**.

### Block B3 — Loop ablation: inference-time-scaling contribution (MUST-RUN)

- **Claim tested**: A4 — is the loop doing the work or is the signal doing the work?
- **Why this block exists**: simplicity check the other way — a reviewer might say "the gain is just inference-time compute, nothing to do with diag_id". This block separates "compute" from "signal".
- **Dataset / split / task**: same NatErr main split.
- **Compared systems**:
  - **DVCR** (T=5, K=4): full method.
  - **DVCR − loop** (T=1, K=4): same method, no iterative refinement. K=4 branches still explore at first turn; verifier still selects best, but no repair trajectory.
  - **DVCR − loop, K=1**: strict zero-shot with the DVCR observation (single sample). Compares against B0 with identical observation.
- **Metrics**: same as B1.
- **Setup details**: same as B1; only T and K change.
- **Success criterion**: DVCR (T=5, K=4) > DVCR − loop (T=1, K=4) ≥ 5 pp with non-overlapping CI. Confirms loop adds real value beyond a single-turn verified best-of-4.
- **Failure interpretation**:
  - DVCR ≈ DVCR − loop (T=1, K=4) → loop unnecessary; paper becomes "verifier-guided best-of-N at first turn", which is simpler but less novel.
  - DVCR − loop (T=1, K=4) already beats B1 heavily → verifier selection at first turn is itself the main win; report honestly.
- **Table / figure target**: Table 2 shared with B2 ablation.
- **Priority**: **MUST-RUN**.

### Block B4 — Rigor audit: contamination floor, evaluation purity, seed variance (MUST-RUN)

- **Claim tested**: A5, A6, A7, and broader evaluation-rigor audit.
- **Why this block exists**: makes the headline numbers defensible. Every reviewer concern from the OOPSLA rejection (data isolation, LLM judge, contamination) is addressed here.
- **Sub-experiments**:
  - **B4a Contamination floor**: run B0 (pre-intervention base model, no SFT, no loop, no reflection) on NatErr main. This is the floor; all gains reported relative to it.
  - **B4b NatErr purity audit**: the pipeline's manifest is checked for (a) commit SHAs ≥ 2025-06-01, (b) no authors-of-this-paper contributions, (c) AST-hash dedup vs any Fuzzlang-LLVM training instance, (d) no `llvm-lit` tests in the main split. Audit artifact released.
  - **B4c Seed variance**: for DVCR and B1, run 3 seeds and report Std / 95% bootstrap CI to confirm gaps are significant, not seed-lucky.
  - **B4d Macro vs micro**: report both macro-average (per-diagnostic-family, unweighted mean across families) and micro-average (per-instance weighted). Head-class inflation shows up as micro − macro gap.
- **Metrics**:
  - Contamination floor = B0 verified_fix_rate on NatErr main.
  - Purity audit = pass/fail per criterion, release manifest.
  - Seed variance = 95% CI width on each reported number.
  - Macro-vs-micro = two numbers per method.
- **Setup details**: B4c runs overlap with B1 runs (B0, B1, DVCR all 3 seeds there).
- **Success criterion**:
  - Contamination floor < DVCR verified_fix_rate with meaningful gap (else paper cannot claim gain).
  - Purity audit: all 4 criteria pass.
  - Seed variance: CI width < 3 pp on DVCR.
  - Macro ≈ Micro (within 2 pp) for DVCR → no head-class inflation. If Macro << Micro, report both honestly.
- **Failure interpretation**:
  - Contamination floor high (>60% on NatErr) → base model is too contaminated; try older Qwen2.5-Coder checkpoint or accept smaller relative gain.
  - Purity audit fails → re-run NatErr harvest with fixed filters before any numbers are reported.
- **Table / figure target**: Table 1 footnote (contamination floor); Table 2 row (macro vs micro); audit artifact in appendix.
- **Priority**: **MUST-RUN**.

### Block B5 — Failure analysis & qualitative diagnosis (MUST-RUN)

- **Claim tested**: where does DVCR still fail, and is the failure pattern interpretable?
- **Why this block exists**: every serious method paper needs a "we are not claiming this solves everything" section. Also, per-diagnostic-family data shows which diagnostics the method handles and which need future work.
- **Sub-experiments**:
  - **B5a Per-family breakdown**: partition NatErr instances by top-level diagnostic family (e.g., `err_expected_*`, `err_undeclared_*`, `err_typecheck_*`, `err_template_*`, `err_redefinition_*`, etc.); report per-family verified_fix_rate for DVCR, B1, and B0.
  - **B5b Dead-end analysis**: for FAIL cases, tabulate the terminal `diag_id` (what the agent could not fix); look for systematic blind spots.
  - **B5c Trivial-deletion-reject rate**: how often the trivial-deletion guard fires — if high, the base model is trying to game the verifier.
  - **B5d Qualitative case studies**: 3-5 hand-selected success + failure cases with full trajectories, printed in the paper to ground the quantitative story.
  - **B5e HPC appendix column** (supports C3, not main): DVCR vs B1 vs B2 on HPC NatErr slice (OpenMP + OpenACC errors from real ECP / Argonne applications).
- **Metrics**: same primary metric stratified.
- **Setup details**: reuses all B1 + B2 + B3 runs; this is post-hoc analysis.
- **Success criterion**:
  - Per-family table shows DVCR wins on > 70% of families (else head-class concern).
  - Dead-end analysis identifies ≤ 3 systematic blind spots (e.g., "DVCR consistently fails on template-instantiation errors").
  - HPC appendix column: DVCR ≥ B1 with a positive direction (does not need to be statistically decisive; appendix-only).
- **Failure interpretation**:
  - DVCR wins on < 50% of families → head-class inflation confirmed; fix macro-avg reporting and tone down headline.
  - Dead-end analysis finds many systematic blind spots → write them as limitations, do not hide.
- **Table / figure target**: Table 3 (per-family), Figure 2 (qualitative cases), Appendix Table A1 (HPC).
- **Priority**: **MUST-RUN** (B5a-d); **NICE-TO-HAVE** for B5e HPC column (but strongly recommended).

---

## Run Order and Milestones

| Milestone | Goal | Runs included | Decision Gate | Wall-clock | Risk |
|---|---|---|---|---|---|
| **M0 Sanity** (W1 early) | Verifier wrapper works; JSON-schema edit parses; trivial hand-crafted case ("missing `;`") fixes in 1 turn. | Unit tests + 1 hand-crafted trajectory. | Gate: hand-crafted case succeeds. If fails, DVCR scaffolding is broken — fix before any dataset runs. | 1-2 days | Very low. |
| **M1 Pipeline build** (W1 late) | DVCR + B1 + B0 + B2-train scaffolding complete. Matched-budget envelope enforced. Cache layer warm. | Build only; no data runs. | Gate: dry-run of 10 synthetic instances through all 4 methods produces valid output + logs. | 3-4 days | Low — mostly plumbing. |
| **M2 NatErr harvest** (W2) | NatErr pipeline runs on 8 projects; dedup + filters + contamination floor measured; scope decision tree applied. | R-PREP1 (harvest), R-PREP3 (dedup audit), R022 (contamination floor = B0 on first 500 → full when available). | **Gate**: NatErr yield bucket (≥3000 / 1000-2999 / 300-999 / <300) determines paper scope. If <300, HALT and escalate. | 5-6 days | **HIGH** — yield is the biggest open variable. |
| **M3 Main table** (W3) | B1 block: 4 methods × 3 seeds on full NatErr main split. | R001-R012 (or equivalent per seed grouping). | **Gate (C1)**: DVCR > B1 with non-overlapping CI? If NO, pause and diagnose (likely a scaffolding bug in DVCR); do not proceed to ablations on a broken foundation. | 5-6 days | Medium — depends on inference farm throughput. |
| **M4 Causal ablations** (W3-W4) | B2 block (3-way signal) + B3 block (loop ablation). | R013-R021 (signal ablation + loop ablation seeds). | **Gate (C2)**: DVCR > DVCR−id significantly? If NO, trigger honest-report path: reframe thesis to "structured-feedback" variant before writing. | 4-5 days | Medium — B2 block requires re-running loops with changed observation channel. |
| **M5 Rigor + failure analysis** (W4) | B4 audit + B5a-d analyses. | Post-hoc over M3/M4 outputs; releases audit manifest. | Gate: macro vs micro gap < 5 pp for DVCR; else rewrite headline with macro number. | 2-3 days | Low — reuses data. |
| **M6 Appendix extras** (W4 late - W5) | B5e HPC column, B3 SFT+stderr-loop, GCC transfer, 32B scale-robustness, DTFT sanity row, T sensitivity, trajectory trim, synthetic stress. | R025-R040 (selective). | No gate — appendix; run what time allows. | variable | Low — additive. |
| **M7 Writing** (W5) | Full paper draft with final tables/figures. | — | Gate: every table/figure has a producing run in the tracker. | W5 | Low. |
| **M8 External review loop** (W6) | `/auto-review-loop` on draft. | — | Gate: score ≥ READY equivalent. | W6 | Medium. |
| **Slack** (+1 week) | Buffer for any M2/M3 gate reopens. | — | — | +1 wk | — |

---

## Compute and Data Budget

### Main paper compute (must-run M0 → M5)

| Component | GPU-hours (A100-40GB) | CPU core-hours | Notes |
|---|---|---|---|
| B2 LoRA SFT training (Qwen2.5-Coder-7B) | ~30 | — | 1 run, ~50k triples, 1 epoch. |
| B0 inference × 3 seeds × 3000 | ~15 | — | Zero-shot single-shot. |
| B1 stderr-loop × 3 seeds × 3000 × (T=5, K=4) | ~80 | — | Biggest inference cost per method. |
| B2 inference × 3 seeds × 3000 | ~15 | — | Same as B0. |
| DVCR × 3 seeds × 3000 × (T=5, K=4) | ~80 | — | |
| DVCR−id × 3 seeds × 3000 × (T=5, K=4) | ~80 | — | |
| DVCR−structure × 3 seeds × 3000 × (T=5, K=4) | ~80 | — | |
| DVCR−loop × 3 seeds × 3000 × (T=1, K=4) | ~16 | — | |
| Clang verifier farm (all methods) | — | ~500 | Dominates CPU; parallelizable. |
| **Main total** | **~400 GPU-hrs** | **~500 core-hrs** | |

### Appendix compute (M6, nice-to-have)

| Component | GPU-hours | Notes |
|---|---|---|
| HPC NatErr slice (500 inst × 4 methods × 3 seeds) | ~30 | |
| B3 SFT+stderr-loop × 3 seeds × 3000 | ~80 | Strongest safety baseline. |
| Qwen2.5-Coder-32B scale robustness (4 methods × 1 seed × 1000) | ~300 | Most expensive item. |
| GCC cross-compiler transfer (1000 inst × DVCR + B1) | ~30 | Needs GCC diag-ID crosswalk; engineering cost. |
| DTFT sanity row (1 seed × 3000) | ~50 | LoRA on DVCR successful rollouts. |
| T ∈ {1,2,3,5,10} budget sweep × DVCR × 1 seed × 1000 | ~40 | |
| Trajectory trim {1, 2, full} × DVCR × 1 seed × 1000 | ~24 | |
| Synthetic stress test (Fuzzlang-Transformer errors × 4 methods × 1 seed × 1000) | ~40 | |
| **Appendix total** | **~600 GPU-hrs** | |

**Grand total**: ~1000 GPU-hours + ~500 CPU core-hours. Fits within a typical Polaris allocation across W1-W5 with 4-8 nodes.

### Data preparation

- **NatErr harvest** (M2): scripted git-walk + CI-log scrape across 8 projects. Docker containers for reproducibility across project toolchains. Expected wall-clock: 3-4 days with 16 parallel workers.
- **Fuzzlang-LLVM training split**: already exists (v1 dataset). Re-filter for AST-hash dedup against NatErr before B2/B3 training.
- **HPC NatErr slice**: curated in parallel with main NatErr from within the same project list (LLVM OpenMP/OpenACC tests are excluded — S3), plus hand-curated from ECP applications (e.g., XSBench, LULESH, miniMD) if the 500 target is not reached from S1/S2.

### Human evaluation needs

**None for the main claim.** Compiler is the oracle. The only human work is:
- Writing qualitative case-study narratives in B5d (~3-5 cases, couple of hours).
- Sanity-checking a random sample of 50 NatErr instances to ensure genuine compile errors (W2 audit).

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| **NatErr yield < 3000** | Claim 1 scope narrows. | Scope decision tree from FINAL_PROPOSAL; narrow to single-project depth study without padding. |
| **NatErr yield < 300** | Submission halted. | Escalate to user; consider 1-year earlier cutoff (2024-10-01) as last resort, label as weakened-isolation variant. |
| **Contamination floor high (>60%)** | Gain relative to floor shrinks. | Report floor honestly; switch to an earlier Qwen2.5-Coder checkpoint (released pre-2025-06) if available; reframe gain relative to floor. |
| **DVCR ≈ DVCR−id** | Typed-ID claim collapses. | Pre-identified in FINAL_PROPOSAL. Rewrite headline to "structured inference-time compiler verifier" and focus main contribution on structure + loop. Still publishable. |
| **DVCR ≈ DVCR−loop (T=1, K=4)** | Loop unnecessary. | Reframe as "verifier-selected best-of-K at first turn"; simpler story. Publishable. |
| **Qwen2.5-Coder JSON-schema compliance fails > 10% at 7B** | Edits rejected too often, distorting matched-budget comparison. | Post-hoc regex parse of free-form output as fallback; count parse-fail as a no-op turn for all methods equally to preserve matched budget. |
| **Clang verifier CPU farm too slow** | M3/M4 wall-clock blows out. | Scale CPU workers; cache by `(code_hash, cmd_hash)`; use `ccache` on headers. |
| **B2 SFT training gets a cursed seed** | Unrepresentative baseline. | 3 seeds for B2 inference even though training is fixed; re-train B2 with different LoRA seed if variance on B2 inference > 5 pp across seeds. |
| **NeurIPS reviewer demands 32B as main** | Headline revision during rebuttal. | 32B appendix row pre-run during W4; if reviewers ask, surface it with one sentence. Do not spend main-paper time on this unless forced. |
| **NeurIPS reviewer demands multi-model (Llama, DeepSeek)** | Rebuttal scramble. | Explicitly argue mechanism-is-base-model-agnostic; 32B appendix handles scale. Multi-family is a future-work bullet, not a rebuttal demand we meet. |

---

## Final Checklist

- [x] Main paper tables are covered (B1 → Table 1, B2/B3 → Table 2, B5a → Table 3).
- [x] Novelty is isolated (B2 three-way verifier-signal ablation).
- [x] Simplicity is defended (B3 loop ablation; trajectory trim in appendix; single search policy locked).
- [x] Frontier contribution is justified (the frontier primitive is verifier-grounded inference-time search; DVCR vs B1 is the direct head-to-head).
- [x] Nice-to-have runs are separated from must-run runs (M6 explicitly appendix).
- [x] Contamination / isolation story is airtight (B4 audit + calendar cut 2025-06-01 + floor).
- [x] Failure analysis included (B5d).
- [x] Matched-budget protocol specified (`E_tokens = 5 × 4 × 256 = 5120` per instance).
- [x] Handoff to `/run-experiment` clear (see EXPERIMENT_TRACKER.md).
