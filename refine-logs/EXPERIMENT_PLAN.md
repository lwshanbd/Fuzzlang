# Experiment Plan (v2, matches FINAL_PROPOSAL.md Round 7 READY)

**Problem**: LLM-based code repair for compilation errors does not close the loop on the compiler's own structured diagnostic output; reported gains collapse under rigorous data isolation.
**Method Thesis**: Typed compiler diagnostics used as an inference-time verifier signal produce measurably better compilation-error repair than stderr-text feedback and static SFT, under **both** rigorous mutation-based evaluation (project-level train/eval holdout + AST-hash dedup) **and** natural-error evaluation (real developer compile errors), at matched inference budgets.
**Date**: 2026-04-23 (v2 cycle)
**Venue**: NeurIPS 2026 main track
**Compute**: Polaris A100-40GB × `diomp`, headline model Qwen2.5-Coder-7B-Instruct; 32B / 70B / frontier API as appendix scale calibration.

---

## Claim Map

| ID | Claim | Why It Matters | Minimum Convincing Evidence | Linked Blocks |
|---|---|---|---|---|
| **C1-A** | **DVCR > B0/B1/B2/B3/B_classical on Column A (mutation eval with project-level holdout + AST-dedup)**, N = 3000, Qwen2.5-Coder-7B matched budget. | Primary statistical claim. Addresses Reviewer C's same-codebase objection directly. | Main table, 3 seeds, non-overlapping 95% bootstrap CIs between DVCR and B1. Absolute gap ≥ 5 pp. | B1, B2 |
| **C1-B** | **DVCR > B1 (stderr-loop) on Column B (NatErr, real developer errors)** at matched budget. | External-validity check. Directly answers Reviewer B's "entirely on synthetic errors" concern. | Directional (positive, same sign on both columns). CI can be looser given smaller N. | B1, B2 |
| **C2** | **DVCR > DVCR − id** on Column A at matched budget. | Typed categorical ID causally isolable from structure in general. Answers Reviewer C's direct ask about diagnostic-ID contribution. | 3-way signal ablation (DVCR / DVCR−id / DVCR−structure), 3 seeds, gap ≥ 3 pp with non-overlapping CI. | B2 |
| **C3** (appendix) | DVCR's lift persists under scale calibration (32B, 70B, optional frontier API) and on HPC directive-parallel subset. | Robustness. Addresses Reviewer B's "stronger models" ask without making scale the headline. | Appendix table showing consistent-direction gains. | B3 |

### Anti-claims explicitly ruled out

| Anti-claim | Ruled out by |
|---|---|
| A1: DVCR's gain is compute / token-budget artifact. | Matched-budget protocol across all methods (same `E_tokens = 5120` envelope per instance). |
| A2: DVCR beats B1 only because of JSON-schema structured interface, not diagnostic ID. | 3-way DVCR − id vs DVCR − structure isolates structure from ID. |
| A3: Mutation-eval is near-duplicate leakage. | Column A uses X/Y project-level holdout + AST-hash dedup across X↔Y + source-provenance-level X-dev carve. Reviewer C's objection. |
| A4: Loop alone explains gain, not typed signal. | DVCR − loop (T=1, K=4) ablation. |
| A5: Contamination — Qwen has seen the commits. | Temporal holdout ≥ 2025-06-01 + measured contamination floor. |
| A6: LLM-as-judge inflates scores. | Compiler is only oracle everywhere. Audit manifest released. |
| A7: DVCR fixes compile but breaks semantics. | **Limitations subset** reports `(compile_ok ∧ tests_pass)` rate on test-covered files with honest gap and case studies. |
| A8: Results depend on silent test-set tuning. | **Model Selection Protocol** (published, §Methodology). All tuning on X-train/X-dev only; Y-eval and NatErr never touched pre-submission. |
| A9: Mechanism is a Clang-only trick. | GCC cross-compiler transfer appendix with diag-ID crosswalk. |
| A10: Only same-codebase eval shown. | Column A is disjoint-projects by construction; Column B is multi-project naturals. |

---

## Paper Storyline

**Main paper must prove**:
- **C1-A** (main 6-row table, Column A) + **C2** (3-way signal ablation on Column A).
- **C1-B** (same 6-row table, Column B column) at whatever honest scale Stage 2 yields.
- Methodology subsection documenting split mechanics + Model Selection Protocol (answers Reviewer A+C directly).
- Limitations subsection with `(compile_ok ∧ tests_pass)` subset (answers Reviewer B).
- Data + code availability committed.

**Appendix supports**:
- **C3** (scale calibration, HPC domain transfer).
- Rigor depth: GCC cross-compiler transfer; per-diagnostic-family breakdown; synthetic-stress in-distribution comparator.
- Mechanism depth: trajectory-trim / budget-T / notes-inclusion / DTFT sanity.

**Experiments intentionally cut**:
- Multi-search-policy comparison (greedy / beam / MCTS).
- Multi-base-family (Llama / DeepSeek / StarCoder) — Qwen2.5-Coder main + scale calibration only.
- Multi-language beyond C/C++ + directive-parallel.
- Retrieval augmentation.
- Full RL (PPO/GRPO/DPO).

---

## Experiment Blocks

### Block B1 — Main two-column table (MUST-RUN, primary)

- **Claims tested**: C1-A and C1-B.
- **Why this block exists**: the 6×2 table is the paper's headline. Without this there is no paper.
- **Dataset / split**:
  - **Column A (Mutation, primary)**: Fuzzlang-Transformer mutations on Y = {PostgreSQL, FFmpeg, Qt, Blender}. N = 3000. Training set is X = {LLVM}, 50k filtered mutations. X-dev carved at source-provenance level (file/function/commit) BEFORE mutation generation. AST-hash dedup across X↔Y.
  - **Column B (Natural)**: NatErr Stage 2 reproductions from 8 projects, commits ≥ 2025-06-01. Eval-only; never in training. N ≈ 100–500 (Stage 2 yield projected).
- **6 methods per column, all Qwen2.5-Coder-7B, matched token envelope** (E_tokens = T×K×256 = 5120):
  - **B0** zero-shot: one LLM call, stderr observation, no loop, no SFT.
  - **B1** stderr-loop: T=5 K=4, stderr text only observation.
  - **B2** static SFT: LoRA on X mutations, single-shot inference.
  - **B3** SFT + stderr-loop: B2 policy + B1's loop.
  - **B_classical** DrRepair (Yasunaga & Liang 2020): prior-era compile-error repair comparator. MACER (Pu et al. 2019) fallback if DrRepair unmaintainable.
  - **DVCR (ours)**: loop + typed diag-ID + JSON edits.
- **Metrics**:
  - Primary: `verified_fix_rate@T=5` (compiler-verified OK under original compile_cmd, whole-file no-regression, trivial-deletion guard), 95% bootstrap CI, 3 seeds.
  - Reported both micro and macro-avg-over-diagnostic-family.
  - Secondary: `token_efficiency`, `avg_turns_to_success`, `avg_verifier_calls`.
- **Success criterion**:
  - Column A: DVCR beats B1 by ≥ 5 pp with non-overlapping 95% CI.
  - Column B: DVCR > B1 directionally (positive gap, same sign), CI can be looser given smaller N.
- **Failure interpretation**:
  - DVCR ≤ B1 on Column A → central thesis refuted; halt and rethink.
  - DVCR > B1 on A but < on B → mutation-regime artifact suspected; report honestly.
- **Table / figure target**: Table 1 (two-column 6-row main).
- **Priority**: **MUST-RUN** both columns.

### Block B2 — Causal ablations (MUST-RUN, on Column A for power)

- **Claims tested**: C2 (typed ID causal) + A2, A4, A8.
- **Dataset**: same Column A eval split (N = 3000, Y projects).
- **Compared systems** (all Qwen2.5-Coder-7B, loop T=5 K=4 except where stated, matched budget):
  - **DVCR** (full): `{diag_id, diag_name, diag_msg, span}`.
  - **DVCR − id**: `{diag_name, diag_msg, span}` (structure without ID).
  - **DVCR − structure**: raw stderr (no typed fields).
  - **DVCR − loop**: T=1 K=4, full observation.
- **Metrics**: same as B1.
- **Success criterion**:
  - DVCR > DVCR − id ≥ 3 pp with non-overlapping CI (typed-ID causal claim).
  - DVCR − id > DVCR − structure ≥ 3 pp (structure-also-helps supporting fact).
- **Failure interpretation**:
  - DVCR ≈ DVCR − id → weaken thesis to "structured inference-time verifier"; anchor still solved; still publishable.
- **Priority**: **MUST-RUN**.

### Block B3 — Rigor audit (MUST-RUN, post-hoc)

- **Sub-experiments**:
  - **B3a** Contamination floor = B0 verified_fix_rate on Column A and Column B. Measured once at submission time.
  - **B3b** Split-purity audit: verify X/Y projects disjoint; AST-hash dedup audit passes; temporal cutoff 2025-06-01 honored on Column B; no paper-author commits.
  - **B3c** Seed variance: 95% bootstrap CI widths on DVCR, B1 on both columns. Target < 3 pp.
  - **B3d** Macro vs micro avg: report both; flag if gap > 2 pp.
  - **B3e** Model Selection Protocol audit trail: publish the log of which decisions were made on X-dev and when final config was frozen. Released with audit manifest.
- **Metrics**: auxiliary to B1/B2; no new main-table cell.
- **Priority**: **MUST-RUN** (all post-hoc on existing runs + protocol metadata).

### Block B4 — Limitations / safety subset (MUST-RUN, appendix figure)

- **Claim tested**: anti-claim A7 (compile-rate ≠ semantic-fix rate).
- **Dataset**: subset of Column A + Column B where the source file is covered by the project's own test suite (e.g., PostgreSQL `regress`, FFmpeg `fate`, Qt tests, Blender tests, LLVM `check-all`).
- **Metric**: `(compile_ok ∧ tests_pass)` rate. Gap vs verified_fix_rate is the honest semantic-fix gap.
- **Priority**: **MUST-RUN** — Reviewer B's specific ask.
- **Case studies**: 3-5 DVCR "successes" where the repair is wrong (compile succeeds, tests fail). Narrated in the appendix.

### Block B5 — Failure analysis (MUST-RUN, post-hoc)

- Per-diagnostic-family breakdown on Column A (Reviewer C's "how much does diag_id help, breakdown?").
- Dead-end `(diag_id, span_hash)` distribution analysis.
- Trivial-deletion-reject rate (how often the guard fires).
- 3-5 qualitative case studies with full trajectories (successes and failures).

### Block C1 — Scale calibration (appendix, NICE-TO-HAVE but strongly recommended)

- **Claim tested**: C3 (robustness).
- **Compute**: Qwen2.5-Coder-32B-Instruct, Llama-3.3-70B-Instruct, and **one optional frontier API cell** (GPT-5 or Claude-4.5, 2026-era) — single seed each, ≤ 1000 instances each.
- **Answers Reviewer B's "stronger baselines" request** without letting scale become a parallel paper.
- **Priority**: **NICE-TO-HAVE** but budget 30 node-hours for it.

### Block C2 — Domain + cross-compiler transfer (appendix)

- HPC slice (OpenMP + OpenACC Stage 2 reproductions from NatErr): DVCR vs B1 on 500 instances.
- GCC cross-compiler transfer with diag-ID crosswalk: DVCR vs B1 on 1000 instances.
- **Priority**: NICE-TO-HAVE.

### Block C3 — Mechanism depth (appendix)

- Budget sensitivity T ∈ {1, 2, 3, 5, 10} on DVCR × 1 seed × 1000.
- Trajectory trim 1 / 2 / full × 1 seed × 1000.
- Notes/macro/template-chain inclusion variant × 1 seed × 1000.
- DTFT sanity (LoRA on DVCR successful trajectories).
- Synthetic in-distribution stress test (DVCR + baselines on X-train mutations — expose the in-distribution vs Y gap).
- **Priority**: NICE-TO-HAVE.

---

## Run Order and Milestones

| Milestone | Goal | Runs included | Gate | Wall | Risk |
|---|---|---|---|---|---|
| **M0 Sanity** (W1 early) | Verifier wrapper + JSON-schema edit parses; hand-crafted missing-`;` smoke passes. | P001, P002, hand-crafted DVCR trajectory. | hand-crafted case fixes in 1 turn. | 1 day | low |
| **M1 Pipeline build** (W1 late) | All 6 methods wired; matched-budget envelope enforced; cache warm. | P003 + method factories + eval harness. | dry-run 10 synthetic instances through 6 methods produces valid logs. | 3 days | low |
| **M2 X/Y split + X-dev carve** (W1-W2) | Source-provenance-level X-dev carve on LLVM; Fuzzlang-Transformer emits mutations on X-train only; Y = {PG, FFmpeg, Qt, Blender} mutation set built. | P009, P011. | AST-hash dedup audit passes across X-train/X-dev AND across X↔Y. | 3 days | **medium** — need clean pre-mutation split infra. |
| **M3 B2 LoRA SFT** (W2) | B2 policy trained on X-train mutations (Fuzzlang v1 recipe). | P008. | held-in validation loss monotonic. | 1 day | low |
| **M4 NatErr Stage 2 (LLVM)** (W2) | Run `scripts/run_natErr_stage2_llvm.py` against the 488 LLVM candidates. | P012. Produces Column B LLVM subset. | reproduction rate measured; either ≥ some threshold → scale Column B, or demote. | 1 day compute + 1 day analysis | medium |
| **M4b NatErr Stage 2 (other projects)** (W2 / in parallel) | Per-project drivers for postgres/ffmpeg/qt. | P013-P015. | target total Column B N. | 3 days | **high** — per-project drivers are real work. |
| **M5 DrRepair setup** (W2) | Install / patch / containerize DrRepair; smoke on 10 instances. MACER fallback ready. | P010. | produces at least one valid fix on at least one instance; rate not needed. | 2-3 days | **medium** — 2020 codebase. |
| **M6 Column A main sweep** (W3) | 6 methods × 3 seeds on Column A (N=3000) at matched budget. | RA001-RA018. | **Gate C1-A**: DVCR > B1 ≥ 5 pp non-overlapping CI. | 5 days (80 node-hours) | medium |
| **M7 Column A ablations** (W3 late) | DVCR − id / − structure / − loop × 3 seeds. | RA019-RA027. | **Gate C2**: DVCR > DVCR-id ≥ 3 pp non-overlapping CI. | 3 days (50 node-hours) | medium |
| **M8 Column B main sweep** (W3-W4) | Same 6 methods × 3 seeds on Column B. | RB001-RB018. | **Gate C1-B**: DVCR > B1 directionally. | 2 days (15 node-hours) | low if M4 yielded enough |
| **M9 Limitations subset** (W4) | Tests-covered instances from both columns; report (compile_ok ∧ tests_pass). | RL001-RL006. | honest reporting; gap expected. | 2 days | low |
| **M10 Appendix runs** (W4) | 32B / 70B / frontier scale cal; HPC; GCC; budget/trim/notes variants. | RC001-RC020. | robustness direction matches. | 3-4 days | low |
| **M11 Writing** (W5) | Paper draft with all tables + figures. | — | every reported number has a run in the tracker. | W5 | medium |
| **M12 External review** (W5-W6) | `/auto-review-loop` on draft. | — | READY-equivalent score. | 1 week | medium |
| **Slack** | buffer before deadline. | — | — | +1 week | — |

---

## Compute and Data Budget

### Main paper (MUST-RUN M6-M9)

| Component | GPU-hours | Node-hours |
|---|---|---|
| B2 LoRA SFT on X-train (one run) | ~30 | 8 |
| Column A sweep: 6 methods × 3 seeds × 3000 instances × 5 turns × 4 branches (for loop methods) / 1 shot (for B0/B2) | ~320 | 80 |
| Column A ablations: 3 × 3 seeds × 3000 × 5×4 | ~200 | 50 |
| Column B sweep: 6 methods × 3 seeds × ~500 instances × loop | ~60 | 15 |
| Limitations subset: re-run existing configs on test-covered slice | ~25 | 7 |
| **Main subtotal** | **~635 GPU-hours** | **~160 node-hours** |

### Appendix (NICE-TO-HAVE M10)

| Component | GPU-hours | Node-hours |
|---|---|---|
| Qwen-32B scale (6 methods × 1 seed × 1000) | ~120 | 30 |
| Llama-3.3-70B scale (2 methods × 1 seed × 500) | ~80 | 20 |
| Frontier API (1 method × 1 seed × 300) | 0 (API) | 0 |
| HPC slice (NatErr OpenMP+OpenACC × 6 methods × 1 seed × 500) | ~30 | 8 |
| GCC cross-compiler (DVCR + B1 × 1 seed × 1000) | ~30 | 8 |
| Budget sensitivity / trim / notes / DTFT / stress | ~50 | 13 |
| **Appendix subtotal** | **~310 GPU-hours** | **~79 node-hours** |

**Grand total**: ~950 GPU-hours / ~240 node-hours.

### Budget reconciliation

150 node-hour budget is **tight** against the 160 node-hour main + 79 node-hour appendix projection. Mitigation tiers:

1. **Drop to 2 seeds** on non-headline main rows (keep 3 seeds only on DVCR and B1): saves ~30 node-hours. Still enough for the headline CI.
2. **Trim Column B to ≤ 300 instances**: saves ~5 node-hours.
3. **Drop Llama-3.3-70B row** (keep 32B only): saves 20 node-hours.
4. **Drop GCC transfer**: saves 8 node-hours.
5. **Drop mechanism-depth variants** (budget sensitivity, trim, notes): saves ~13 node-hours.

Applying (1)-(3): ~195 node-hours total, fits 150 budget with ~10 hours buffer if we additionally drop (4). If Pine cluster provides the Column A sweep instead of Polaris (CPU-rich with GPU access), Polaris can keep only the scale-calibration cells.

### CPU-side budget (NatErr Stage 2 + DrRepair training/install)
- LLVM Stage 2: one baseline LLVM build (~30 CPU-hours on 32 cores) + per-candidate reproduction (~1-2 CPU-hours at 16 workers).
- Per-project Stage 2 drivers (postgres, ffmpeg, qt, blender): 1-3 CPU-days each to write + smoke.
- DrRepair/MACER env containerization: ~3 CPU-days of eng.

### Human effort
- Case study narratives in Block B5: 2-3 days of writing.
- 50-instance random sanity check of Column A and Column B post-dedup: 0.5 day.

---

## §Methodology (paper subsection — lives here so there is a single source of truth)

### Split mechanics
1. **X / Y project-level holdout** for Column A: X = {LLVM}, Y = {PostgreSQL, FFmpeg, Qt, Blender}. No shared projects.
2. **Source-provenance X-dev carve**: X = LLVM is partitioned at file/function/commit level **before** mutation generation. Mutations of same underlying function cannot appear in both X-train and X-dev.
3. **AST-hash dedup** across X↔Y: 5-line-window AST-hash computed on every Column A eval instance, rejected if it collides with any X-train hash.
4. **Temporal holdout** for Column B: NatErr commits ≥ 2025-06-01.
5. **Diagnostic-family stratification**: some Column A instances drawn from families absent from X-train (generalization check).
6. **Contamination floor**: pre-intervention base-model verified_fix_rate on Column A + Column B. Measurement *procedure* locked on X-dev; *values* measured on the eval sets at submission time.
7. **Compiler oracle**: Fuzzlang-patched clang is the only success signal. No LLM judge.

### Model Selection Protocol
Locked on **X-train / X-dev only**:
- Prompts (all three signal modes)
- LoRA rank/alpha/LR/epochs for B2/B3/DTFT
- T, K, temperature, span window L, trajectory retention N
- DVCR edit schema
- Dead-end respawn rule
- Contamination-floor measurement procedure

**Never touched for tuning**:
- Column A eval (Y mutations)
- Column B eval (NatErr)
- All appendix eval subsets

Audit trail archived; frozen configs hash-committed before eval numbers are generated.

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| **NatErr Stage 2 yield < 100** | Column B underpowered. | Demote Column B to appendix (already in plan); paper rests on Column A with explicit "natural external-validity reported at honest scale". |
| **DrRepair unmaintainable in 2026** | B_classical row empty. | MACER (2019) fallback ready. BIFI third-resort. |
| **Qwen2.5-Coder cutoff undocumented → contamination concern** | Reviewer skepticism on Column B. | Contamination floor measurement supplies ground truth independent of cutoff documentation. |
| **DVCR ≈ DVCR − id** | Typed-ID causal claim collapses. | Thesis weakens to "structured inference-time compiler verifier". Anchor still solved; publishable. |
| **70B / frontier closes the gap** | Robustness claim in reverse. | Honest finding; paper framing pivots to "small-model enabler" — still a meaningful result. |
| **Budget overrun** | Appendix cells cut. | Tier-1 drops (2 seeds on non-headline rows, 70B cut, GCC cut) defined above; total fits within 150 node-hours. |
| **X-dev leak into Y via transitive dedup failure** | Headline invalidated. | AST-hash dedup audit (Block B3b) run BEFORE main sweep; block gate. |
| **Model-selection protocol drift** (e.g., hyperparameter peek at Y) | Headline invalidated. | Configs hash-frozen before eval runs; audit trail committed to repo. |

---

## Final Checklist

- [x] Main paper tables covered (B1 → Table 1 two-column, B2 → Table 2 ablation, B5a → Table 3 per-family).
- [x] Novelty isolated (B2 three-way verifier-signal ablation).
- [x] Simplicity defended (B2 loop ablation).
- [x] Frontier leverage justified (inference-time verifier-grounded search).
- [x] Nice-to-have runs separated from must-run.
- [x] Contamination / isolation story airtight (B3 audit + Model Selection Protocol).
- [x] Failure / limitations analysis included (B4 test-covered subset + B5 case studies).
- [x] Cross-codebase eval (Column A Y-projects + Column B multi-project NatErr).
- [x] Classical-repair comparator (B_classical = DrRepair / MACER).
- [x] Stronger-model calibration appendix (32B + 70B + optional frontier).
- [x] Model Selection Protocol published; no silent test-set tuning.
- [x] Data + code availability committed (HuggingFace + GitHub + audit manifest).
- [x] Matched-budget protocol specified (E_tokens = 5120 per instance).
- [x] Handoff to `/run-experiment` clear (see EXPERIMENT_TRACKER.md).
