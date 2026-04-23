# Experiment Tracker

> Flat run-level table. Each row = one (method × split × seed × config) combination that produces data for one cell / column in the paper tables. Update `Status` as runs launch. MUST = main-paper; NICE = appendix or rebuttal-defense.

**Base model (main)**: Qwen2.5-Coder-7B-Instruct · FP16 · vLLM
**Base model (appendix)**: Qwen2.5-Coder-32B-Instruct
**Eval split (main)**: NatErr commits ≥ 2025-06-01 across {LLVM, Chromium, FFmpeg, LibreOffice, PostgreSQL, Blender, Qt, Bitcoin Core}
**Matched output-token envelope per instance**: `E_tokens = T × K × 256 = 5120` for loop methods; same in one shot for single-shot methods
**Seeds (main)**: `{17, 23, 42}`

---

## Preparation runs

| Run ID | Milestone | Purpose | System / Variant | Split | Metrics | Priority | Status | Notes |
|---|---|---|---|---|---|---|---|---|
| P001 | M0 | Verifier wrapper unit tests + JSON-schema edit parser tests | Verifier V + agent π scaffolding | N/A | unit-test pass rate | MUST | TODO | 5-10 hand-crafted cases including "missing `;`", "undeclared var", "pointer/int mismatch" |
| P002 | M0 | Hand-crafted DVCR end-to-end smoke test | DVCR full | 5 synthetic (buggy, cmd) | verified_fix_rate (target 5/5) | MUST | TODO | Proves scaffolding not broken before any dataset run |
| P003 | M1 | Dry-run 10-instance pipeline through all 4 main methods | B0, B1, B2, DVCR | 10 instances | sanity only | MUST | TODO | Confirms matched-budget enforcement + logging |
| P004 | M2 | NatErr harvest run (S1 git-history + S2 CI scrape) | — | 8 projects, ≥2025-06-01 | yield count, dedup-survival rate | MUST | TODO | 3-4 days wall-clock with 16 workers; dominates W2 |
| P005 | M2 | NatErr AST-hash dedup audit vs Fuzzlang-LLVM training | — | NatErr candidates | duplicates removed, final n | MUST | TODO | Feeds scope decision tree |
| P006 | M2 | Random sample of 50 NatErr instances, human sanity check | — | 50 instances | pass/fail for "genuine compile error" | MUST | TODO | Catches harvest bugs before Gate M2 |
| P007 | M2 | Manifest generation for audit artifact | — | NatErr final split | per-instance `(project, sha, file, line, diag_id)` | MUST | TODO | Released alongside paper |
| P008 | M2 | B2 LoRA SFT training (Qwen2.5-Coder-7B on Fuzzlang-LLVM train) | LoRA rank-16, 1 ep | Fuzzlang-LLVM train (AST-dedup'd vs NatErr) | training loss, held-in val | MUST | TODO | ~30 GPU-hrs; one run, single seed |

---

## Block B1 — Main 4-row table (C1)

| Run ID | Milestone | Purpose | System / Variant | Split | Metrics | Priority | Status | Notes |
|---|---|---|---|---|---|---|---|---|
| R001 | M3 | B0 zero-shot baseline | B0 | NatErr main, seed 17 | verified_fix_rate@T=5, token_eff | MUST | TODO | Doubles as contamination floor B4a |
| R002 | M3 | B0 seed 23 | B0 | NatErr main, seed 23 | — | MUST | TODO | |
| R003 | M3 | B0 seed 42 | B0 | NatErr main, seed 42 | — | MUST | TODO | |
| R004 | M3 | B1 stderr-loop | B1 | NatErr main, seed 17 | verified_fix_rate@T=5, token_eff, avg_turns | MUST | TODO | Strongest non-ours baseline |
| R005 | M3 | B1 seed 23 | B1 | NatErr main, seed 23 | — | MUST | TODO | |
| R006 | M3 | B1 seed 42 | B1 | NatErr main, seed 42 | — | MUST | TODO | |
| R007 | M3 | B2 static SFT | B2 | NatErr main, seed 17 | verified_fix_rate@T=5 | MUST | TODO | Uses P008 LoRA weights |
| R008 | M3 | B2 seed 23 | B2 | NatErr main, seed 23 | — | MUST | TODO | |
| R009 | M3 | B2 seed 42 | B2 | NatErr main, seed 42 | — | MUST | TODO | |
| R010 | M3 | **DVCR** full | DVCR | NatErr main, seed 17 | all primary + secondary | MUST | TODO | **Headline number** |
| R011 | M3 | DVCR seed 23 | DVCR | NatErr main, seed 23 | — | MUST | TODO | |
| R012 | M3 | DVCR seed 42 | DVCR | NatErr main, seed 42 | — | MUST | TODO | |

**Gate (C1)**: mean(R010-R012).verified_fix_rate − mean(R004-R006).verified_fix_rate ≥ 5 pp **and** their 95% bootstrap CIs do not overlap. If fail, pause and diagnose before running ablations.

---

## Block B2 — Three-way verifier-signal ablation (C2)

| Run ID | Milestone | Purpose | System / Variant | Split | Metrics | Priority | Status | Notes |
|---|---|---|---|---|---|---|---|---|
| R013 | M4 | DVCR − id (structured, no ID) | DVCR−id: obs = `{diag_name, diag_msg, span}` | NatErr main, seed 17 | verified_fix_rate@T=5 | MUST | TODO | Middle cell — isolates ID from structure |
| R014 | M4 | DVCR − id seed 23 | DVCR−id | NatErr main, seed 23 | — | MUST | TODO | |
| R015 | M4 | DVCR − id seed 42 | DVCR−id | NatErr main, seed 42 | — | MUST | TODO | |
| R016 | M4 | DVCR − structure (stderr only) | DVCR−structure: obs = raw stderr text | NatErr main, seed 17 | verified_fix_rate@T=5 | MUST | TODO | Should approximate B1 |
| R017 | M4 | DVCR − structure seed 23 | DVCR−structure | NatErr main, seed 23 | — | MUST | TODO | |
| R018 | M4 | DVCR − structure seed 42 | DVCR−structure | NatErr main, seed 42 | — | MUST | TODO | |

**Gate (C2)**: mean(R010-R012) − mean(R013-R015) ≥ 3 pp with non-overlapping CI. If fail, trigger honest-report path — rewrite thesis to "structured-feedback" variant.

---

## Block B3 — Loop ablation (A4)

| Run ID | Milestone | Purpose | System / Variant | Split | Metrics | Priority | Status | Notes |
|---|---|---|---|---|---|---|---|---|
| R019 | M4 | DVCR − loop (T=1, K=4) | DVCR (T=1, K=4) | NatErr main, seed 17 | verified_fix_rate | MUST | TODO | Isolates loop from verifier selection at first turn |
| R020 | M4 | DVCR − loop seed 23 | DVCR (T=1, K=4) | NatErr main, seed 23 | — | MUST | TODO | |
| R021 | M4 | DVCR − loop seed 42 | DVCR (T=1, K=4) | NatErr main, seed 42 | — | MUST | TODO | |
| R019b | M4 | DVCR − loop − breadth (T=1, K=1) | DVCR (T=1, K=1) | NatErr main, seed 17 | verified_fix_rate | MUST | TODO | Strictest single-sample baseline with DVCR observation; compares to B0 with identical obs |
| R020b | M4 | R019b seed 23 | DVCR (T=1, K=1) | NatErr main, seed 23 | — | MUST | TODO | |
| R021b | M4 | R019b seed 42 | DVCR (T=1, K=1) | NatErr main, seed 42 | — | MUST | TODO | |

---

## Block B4 — Rigor audit (post-hoc; no new runs)

| Item | Milestone | Source | Purpose | Priority | Status | Notes |
|---|---|---|---|---|---|---|
| B4a | M5 | R001-R003 | Contamination floor = mean B0 verified_fix_rate on NatErr main | MUST | TODO | Reported in Table 1 footnote |
| B4b | M5 | P004-P007 | NatErr purity audit — 4 criteria check | MUST | TODO | Audit manifest released |
| B4c | M5 | R001-R021b | Seed variance 95% bootstrap CI per reported number | MUST | TODO | CI width < 3 pp target |
| B4d | M5 | R001-R021b | Macro vs micro average per method | MUST | TODO | Flags head-class inflation |

---

## Block B5 — Failure analysis (post-hoc; one HPC run set is new)

| Run ID | Milestone | Purpose | System / Variant | Split | Metrics | Priority | Status | Notes |
|---|---|---|---|---|---|---|---|---|
| B5a | M5 | Per-diagnostic-family breakdown | DVCR, B1, B0 | NatErr main | per-family verified_fix_rate | MUST | TODO | Post-hoc over M3 logs |
| B5b | M5 | Dead-end analysis | DVCR FAIL cases | NatErr main | terminal diag_id distribution | MUST | TODO | Post-hoc over R010-R012 logs |
| B5c | M5 | Trivial-deletion-reject rate | DVCR | NatErr main | trivial-deletion-reject % | MUST | TODO | Post-hoc over R010-R012 logs |
| B5d | M5 | Qualitative case studies | DVCR successes + failures | NatErr main | 3-5 narrated trajectories | MUST | TODO | Writing task, not a run |
| R025 | M6 | HPC appendix column — B0 | B0 | HPC NatErr slice (500), seed 17 | verified_fix_rate | NICE | TODO | Supports C3; single seed OK for appendix |
| R026 | M6 | HPC — B1 | B1 | HPC slice, seed 17 | — | NICE | TODO | |
| R027 | M6 | HPC — B2 | B2 | HPC slice, seed 17 | — | NICE | TODO | |
| R028 | M6 | HPC — DVCR | DVCR | HPC slice, seed 17 | — | NICE | TODO | Headline for Appendix Table A1 |
| R029 | M6 | HPC — DVCR seed 23 | DVCR | HPC slice, seed 23 | — | NICE | TODO | Only DVCR gets 3 seeds on HPC |
| R030 | M6 | HPC — DVCR seed 42 | DVCR | HPC slice, seed 42 | — | NICE | TODO | |

---

## Appendix runs (M6, NICE-TO-HAVE, rebuttal-defense ready)

| Run ID | Milestone | Purpose | System / Variant | Split | Metrics | Priority | Status | Notes |
|---|---|---|---|---|---|---|---|---|
| R031 | M6 | B3 SFT + stderr-loop safety baseline | B3 = B2-SFT'd + stderr-loop (T=5, K=4) | NatErr main, seed 17 | verified_fix_rate | NICE | TODO | Surfaced to main if a reviewer insists |
| R032 | M6 | B3 seed 23 | B3 | NatErr main, seed 23 | — | NICE | TODO | |
| R033 | M6 | B3 seed 42 | B3 | NatErr main, seed 42 | — | NICE | TODO | |
| R034 | M6 | 32B scale robustness — DVCR | DVCR (Qwen2.5-Coder-32B) | NatErr main subset (1000), seed 17 | verified_fix_rate | NICE | TODO | Most expensive appendix item; ~300 GPU-hrs |
| R035 | M6 | 32B robustness — B1 | B1 (32B) | same 1000, seed 17 | — | NICE | TODO | Confirms mechanism is not 7B-specific |
| R036 | M6 | 32B robustness — B0 | B0 (32B) | same 1000, seed 17 | — | NICE | TODO | |
| R037 | M6 | GCC cross-compiler transfer | DVCR + B1 via GCC verifier + diag-ID crosswalk | GCC NatErr subset (1000), seed 17 | verified_fix_rate | NICE | TODO | Engineering cost: GCC diag-ID crosswalk table |
| R038 | M6 | DTFT sanity check | DVCR + LoRA on successful rollouts | NatErr main, seed 17 | verified_fix_rate | NICE | TODO | One-row appendix; shows zero-training stance is not load-bearing |
| R039 | M6 | Budget sensitivity T={1,2,3,5,10} | DVCR | NatErr subset (1000), seed 17 | verified_fix_rate vs T | NICE | TODO | Curve for Appendix Fig A1 |
| R040 | M6 | Trajectory trim {1, 2, full} | DVCR | NatErr subset (1000), seed 17 | verified_fix_rate vs trim | NICE | TODO | Justifies "last 2 turns" default |
| R041 | M6 | Notes / macro / template variant | DVCR + notes-inclusion | NatErr subset (1000), seed 17 | verified_fix_rate | NICE | TODO | Tests whether dropping notes hurts |
| R042 | M6 | Synthetic stress test | DVCR, B1, B0 | Fuzzlang-Transformer errors (1000) | verified_fix_rate | NICE | TODO | Shows natural↔synthetic gap; anchors to Fuzzlang v1 numbers |

---

## Status legend

- `TODO` — not started
- `RUNNING` — in progress
- `DONE` — data collected, not yet in paper
- `PAPER` — results locked in a table/figure
- `BLOCKED` — gate failure or dependency unresolved
- `CANCELLED` — decided against

---

## Reality checks before launch

- [ ] P001 verifier unit tests passing
- [ ] P002 hand-crafted DVCR trajectory succeeds
- [ ] P003 dry-run of 4 methods on 10 synthetic instances produces valid logs
- [ ] P004 NatErr harvest yields > 300 before committing to scope
- [ ] P005 dedup leaves > 80% of harvested errors
- [ ] P006 human sanity check passes on 50 sampled instances
- [ ] P008 B2 LoRA SFT validation loss monotonic (no training bug)
- [ ] Matched-budget envelope `E_tokens = 5120` enforced in harness for all loop and single-shot methods
- [ ] 95% bootstrap CI computation wired before M3 launches

---

## Handoff

`/run-experiment` can consume this tracker directly. Run IDs are stable. Gate failures trigger pauses, not workarounds.
