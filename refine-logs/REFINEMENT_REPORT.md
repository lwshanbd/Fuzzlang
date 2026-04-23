# Refinement Report

**Problem**: rewrite the rejected OOPSLA Fuzzlang paper for NeurIPS 2026.
**Initial Approach**: combine Agent code repair + fine-tuning + compiler cooperation.
**Date**: 2026-04-23
**Rounds**: 4 / 5
**Final Score**: **9.2 / 10**
**Final Verdict**: **READY**
**Thread**: `019db833-f01f-7753-a705-e9b1cb416d09`

## Problem Anchor (verbatim, preserved across all 4 rounds)
See `refine-logs/PROBLEM_ANCHOR.md`. Anchored to: compiler diagnostic is the cheapest precise repair signal; no LLM pipeline closes the loop on it; reported gains collapse under rigorous isolation + compiler-oracle eval. Non-goals, constraints, success condition unchanged.

## Output Files
- Review summary: `refine-logs/REVIEW_SUMMARY.md`
- Final clean proposal: `refine-logs/FINAL_PROPOSAL.md`
- Literature scan: `refine-logs/LITERATURE_SCAN.md`
- Per-round: `round-{0..4}-{initial-proposal | review | refinement}.md`
- Score history: `refine-logs/score-history.md`
- State: `refine-logs/REFINE_STATE.json`

## Score Evolution

| Round | Problem Fidelity | Method Specificity | Contribution Quality | Frontier Leverage | Feasibility | Validation Focus | Venue Readiness | Overall | Verdict | Drift |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 9 | 7 | 7 | 9 | 6 | 5 | 6 | 7.4 | REVISE | NONE |
| 2 | 9 | 8 | 8 | 9 | 8 | 8 | 8 | 8.3 | REVISE | NONE |
| 3 | 9 | 9 | 9 | 9 | 8 | 8 | 9 | 8.9 | REVISE | NONE (conditional) |
| 4 | 10 | 9 | 9 | 9 | 9 | 9 | 9 | **9.2** | **READY** | **NONE** |

Weighting used: PF 15 + MS 25 + CQ 25 + FL 15 + F 10 + VF 5 + VR 5.

## Round-by-Round Review Record

| Round | Main Reviewer Concerns | What Was Changed | Result |
|---|---|---|---|
| 1 | Contribution sprawl; GCC, multi-scale, DTFT, multi-search all on critical path; bloated matrix; paper identity not frozen. | Headline locked to one sentence; main table 4 rows + 2 ablations; single 32B; JSON-schema action; parallel-sampling+verifier; GCC/DTFT/multi-scale → appendix. | Resolved. |
| 2 | `diag_id → stderr` ablation confounded; no multi-diag rule; `span_hash` undefined; "post-cutoff" wording fragile; missing B3 safety. | 3-way verifier-signal ablation; primary-diagnostic-only rule; precise `span_hash`; calendar-cut + measured contamination floor; B3 appendix-ready; trajectory trim to last 2 turns; HPC column with demote-fallback. | Resolved. |
| 3 | Latent drift risk: synthetic-pad fallback for sparse naturals; no pre-specified harvesting protocol. | Evaluation-Purity Rule; NatErr pipeline (S1 git-history + S2 CI logs; S3 `llvm-lit` excluded); fixed project list; filters + dedup + audit manifest; scope decision tree; HPC fully → appendix. | Resolved. |
| 4 | — | — | READY. |

## Final Proposal Snapshot

Final clean version: `refine-logs/FINAL_PROPOSAL.md`. Summary in 5 bullets:

- **Thesis**: typed compiler diagnostics as inference-time verifier signal beats stderr feedback and static SFT under rigorous isolation on natural C/C++ compilation errors at matched budget.
- **Mechanism**: `V(code, cmd) → {status, diag_id, diag_name, diag_msg, span}` with primary-diagnostic-only rule; agent π conditions on span snippet + 488-class diag_id + last-2-turn trajectory; action = JSON `{start_line, end_line, replacement}` schema-constrained to span ±5; K=4 parallel proposals + exact verifier selection; T=5; span-hash dead-end detection.
- **Main table**: 4 rows (B0 zero-shot / B1 stderr-loop / B2 static SFT / DVCR) at matched Qwen2.5-Coder-32B and matched token budget on NatErr natural-errors-only split.
- **Causal ablations**: 3-way verifier signal (full / no-id / no-structure) + loop-off. DVCR vs DVCR−id is the typed-ID causal claim.
- **Evaluation**: NatErr pipeline (git-history fault harvest + CI-log scrape on 8 projects, post 2024-10-01); audit-manifest released; scope decision tree prevents synthetic padding; contamination floor replaces fragile cutoff claims.

## Method Evolution Highlights
1. **Biggest simplification**: the R0 proposal had DTFT, GCC transfer, multi-scale, multi-budget, and multi-search all on the critical path as "optional but interesting". R1 reviewer forced all of them into appendix. The paper became a method paper, not a benchmark paper.
2. **Biggest causal-isolation upgrade**: R2 replaced the 2-way `diag_id → stderr` ablation with a 3-way (full / no-id / no-structure). Separates "structure in general" from "typed categorical ID on top of structure" — previously confounded.
3. **Biggest integrity upgrade**: R3 promoted an implicit convention (use natural errors) to a paper-level **Evaluation-Purity Rule** with a fixed NatErr pipeline, explicit dedup, and a scope decision tree that forbids synthetic padding ever. This closed a latent drift route (R2 had "supplement with synthetic" as a risk mitigation; R3 caught that was itself drift).
4. **Biggest modernity move (preserved throughout)**: JSON-schema structured-output action + parallel sampling with exact verifier selection (instead of beam/MCTS/learned scorer). Aligned with AlphaCodium / Large Language Monkeys / Archon lineage.

## Pushback / Drift Log

| Round | Reviewer Said | Author Response | Outcome |
|---|---|---|---|
| 1 | Delete DTFT from main plan. | Accepted. Kept as one-row appendix sanity check (user's original framing preserved the "fine-tune + agent" direction; appendix-only preserves that intellectual interest without diluting headline). Noted in R1 refinement that we could re-escalate DTFT to co-equal if user disagrees. | Accepted. |
| 2 | Confounded `diag_id → stderr` ablation. | Accepted; replaced with clean 3-way. | Accepted. |
| 3 | Synthetic padding of naturals would be drift. | Accepted fully; replaced with scope decision tree (shrink, never pad). | Accepted. |

No reviewer feedback was rejected on drift grounds. The reviewer's instincts and the anchor were aligned throughout.

## Remaining Weaknesses (honest)

1. **NatErr yield dependency** (executional). If fewer than 3000 natural errors are harvestable post 2024-10-01 from the fixed project list, the scope narrows per the decision tree. This is principled, not a surprise, but the paper's scale could be smaller than ideal.
2. **Typed-ID vs structure**. The central causal claim is that typed `diag_id` beats structured-but-untyped feedback. If empirically `DVCR ≈ DVCR − id`, the thesis weakens to "structured inference-time compiler verifier beats stderr-loop and SFT", which is still publishable but one step less novel.
3. **Single-compiler main scope**. GCC cross-compiler transfer is appendix only; reviewers could push it into the main. Defended by simplicity-first argument, but the community's tolerance for single-compiler main results at NeurIPS 2026 is uncertain.
4. **Single-base-model main scope**. Same argument as above; reviewers may want 7B and 70B in main.

## Raw Reviewer Responses
See `refine-logs/round-{1..4}-review.md` for full verbatim responses inside `<details>` blocks.

## Next Steps

Verdict READY. Recommended handoff per the research-refine skill:

1. **`/experiment-plan`** — turn this FINAL_PROPOSAL into a claim-by-claim experiment roadmap with concrete runs, seeds, compute requests, and gating criteria.
2. **`/experiment-bridge`** then **`/run-experiment`** — implement the DVCR scaffolding + NatErr pipeline on Polaris under project `diomp`.
3. **`/auto-review-loop`** — iterate once results are in.
4. **`/paper-writing`** — produce the NeurIPS 2026 PDF when experiments converge.

Before handoff: user confirmed (2026-04-23) the four decision points as follows:
- (a) Project list: **confirmed** {LLVM, Chromium, FFmpeg, LibreOffice, PostgreSQL, Blender, Qt, Bitcoin Core}.
- (b) Calendar cut: **pushed to 2025-06-01** (was 2024-10-01). Prior date sat on Qwen2.5-Coder's training-cutoff border; later date gives an 8+ month contamination buffer while leaving 10+ months of natural-error commit history through 2026-04-23.
- (c) Base model: **Qwen2.5-Coder-7B-Instruct for main table and all causal ablations; Qwen2.5-Coder-32B-Instruct moves to appendix scale-robustness row**. Rationale: Polaris 4×A100-40GB has tooling risk for 32B LoRA (needed only for B2/B3 SFT baselines); mechanism is not scale-dependent; 7B is a same-scale successor to Fuzzlang v1's Llama-3-8B headline and enables multi-seed variance reporting.
- (d) DTFT: **remain in appendix, do not escalate**. R1 reviewer's "second paper inside the first" critique stands; one dominant contribution.

Round 5 (post-READY sanity check on (b) and (c)) confirmed READY verdict preserved with both changes. See `round-5-sanity-check.md`.
