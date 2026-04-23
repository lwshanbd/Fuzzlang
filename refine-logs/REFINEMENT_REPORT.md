# Refinement Report (v1 + v2 cycles)

**Problem**: rewrite the rejected OOPSLA Fuzzlang paper for NeurIPS 2026.
**Initial approach**: combine Agent code repair + fine-tuning + compiler cooperation.
**Date**: 2026-04-23
**Rounds**: v1 = R1–R4 (+ R5 sanity); v2 = R6–R7
**Final Score**: **9.3 / 10**
**Final Verdict**: **READY**
**Thread**: `019db833-f01f-7753-a705-e9b1cb416d09` (continuous across both cycles)

## Problem Anchor
See `refine-logs/PROBLEM_ANCHOR.md`. Bottom-line problem immutable across both cycles. Success condition amended on 2026-04-23 after verbatim OOPSLA reviewer text was recovered (see `OOPSLA_REVIEWS.md`).

## Output Files
- `PROBLEM_ANCHOR.md` — frozen anchor with 2026-04-23 evidence-standard addendum
- `OOPSLA_REVIEWS.md` — verbatim OOPSLA reviewer text (load-bearing for v2 cycle)
- `LITERATURE_SCAN.md` — 2024–2026 related work by bucket
- `FINAL_PROPOSAL.md` — canonical v2 final proposal
- `REVIEW_SUMMARY.md` — both-cycles evolution summary
- `round-0-initial-proposal.md` — v1 cycle round 0
- `round-{1..4}-{review,refinement}.md` — v1 cycle rounds
- `round-5-sanity-check.md` — post-v1 sanity
- `round-6-initial-proposal.md` — v2 cycle reopen round
- `round-{6,7}-review.md` — v2 cycle reviews
- `round-7-refinement.md` — v2 cycle final refinement
- `score-history.md` — full score table across both cycles

## Score Evolution (all rounds)

| Round | Problem Fidelity | Method Specificity | Contribution Quality | Frontier Leverage | Feasibility | Validation Focus | Venue Readiness | Overall | Verdict | Drift | Note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 9 | 7 | 7 | 9 | 6 | 5 | 6 | 7.4 | REVISE | NONE | v1 initial |
| 2 | 9 | 8 | 8 | 9 | 8 | 8 | 8 | 8.3 | REVISE | NONE | v1 |
| 3 | 9 | 9 | 9 | 9 | 8 | 8 | 9 | 8.9 | REVISE | cond. | v1 |
| 4 | 10 | 9 | 9 | 9 | 9 | 9 | 9 | 9.2 | READY | NONE | v1 end |
| 5 | 10 | 9 | 9 | 9 | 9 | 9 | 9 | 9.2 | READY | NONE | sanity |
| **6** | **10** | **9** | **9** | **9** | **8** | **9** | **9** | **9.1** | **READY** | **NONE** | **v2 reopen** |
| **7** | **10** | **9** | **9** | **9** | **8** | **9** | **9** | **9.3** | **READY** | **NONE** | **v2 end** |

Weighting used: PF 15 + MS 25 + CQ 25 + FL 15 + F 10 + VF 5 + VR 5.

## Round-by-Round Review Record (all rounds)

| Round | Cycle | Main Reviewer Concerns | What Was Changed | Result |
|---|---|---|---|---|
| 1 | v1 | Contribution sprawl; multi-axis critical path; bloated matrix. | Headline locked; 4-row main + 2 ablations; single base model; JSON-schema action. | REVISE → sharper |
| 2 | v1 | Confounded ablation; missing multi-diag rule; fragile cutoff wording. | 3-way signal ablation; primary-diag rule; span_hash defined; calendar cut + floor; B3 appendix. | REVISE → tight |
| 3 | v1 | Latent synthetic-pad drift risk; no harvesting protocol. | Evaluation-Purity Rule (natural-only); NatErr pipeline. | REVISE → anchor-safe |
| 4 | v1 | — | — | **READY 9.2** |
| 5 | v1 | Post-READY feasibility changes. | 32B → 7B main; cutoff 2024-10 → 2025-06. | READY preserved |
| 6 | v2 | Verbatim OOPSLA reviews showed R3 drift warning was on the wrong evidence standard; Stage 2 yield is halt-borderline; missing classical baseline + scale cal + split mechanics + limitations. | Two-column main table (mutation + natural); DrRepair; 70B appendix; Methodology subsection; limitations subsection; data-availability commits. | **READY 9.1** |
| 7 | v2 | Hidden-validity: model selection could silently tune on Y/NatErr. | Model Selection Protocol subsection; X-dev carved at source-provenance; floor protocol locked on X-dev, values on Y/NatErr. | **READY 9.3** |

## Final Proposal Snapshot

Canonical clean version: `refine-logs/FINAL_PROPOSAL.md`. Summary in 5 bullets:

- **Thesis**: typed compiler diagnostics as inference-time verifier signal beats stderr feedback and static SFT, under **both** rigorous mutation-with-holdout and natural-error regimes, at matched budgets.
- **Mechanism (unchanged since v1)**: `V(code, cmd) → {status, diag_id, diag_name, diag_msg, span}` with primary-diag rule; agent π conditions on span + ID + last-2-turn trajectory; K=4 parallel samples + exact verifier; T=5; span-hash dead-end; JSON-schema edit.
- **Main table (v2)**: two columns × six rows. Column A = mutation on Y disjoint from X-train, N=3000, AST-dedup, primary claim. Column B = NatErr naturals, N=100-500, external validity. Rows: B0, B1, B2, B3, **B_classical DrRepair**, DVCR.
- **Causal ablations**: 3-way verifier signal + loop-off on Column A.
- **Rigor protocol**: §Methodology covers split mechanics + Model Selection Protocol (X-train/X-dev only for tuning; Y and NatErr never touched). Audit manifest released.

## Method Evolution Highlights

1. **Biggest framing upgrade (v2 R6)**: moved from natural-only eval to Column A (mutation, rigorous holdout) + Column B (natural, eval-only). Triggered by verbatim Reviewer C "not just injected" + empirical yield showing natural-only at halt threshold. Fixed both the scale problem and the external-validity problem simultaneously.
2. **Biggest rigor upgrade (v2 R7)**: Model Selection Protocol makes explicit that prompts/hyperparameters/schema are tuned only on X-train/X-dev; Y-eval and NatErr are untouched until submission. Closes the hidden-tuning concern that would otherwise invalidate the main claim.
3. **Biggest causal-isolation upgrade (v1 R2)**: 3-way verifier-signal ablation (full / no-id / no-structure) separates "structure" from "typed ID".
4. **Biggest simplification (v1 R1)**: locked one main table + two ablations; demoted DTFT/GCC/multi-scale/multi-search to appendix. Prevented contribution sprawl.
5. **Biggest baseline addition (v2 R6)**: DrRepair as B_classical gives a prior-era comparator per Reviewer B.

## Pushback / Drift Log

| Round | Reviewer Said | Author Response | Outcome |
|---|---|---|---|
| 1 | Delete DTFT from main plan. | Accepted; DTFT appendix-only row. | Accepted |
| 2 | Confounded diag_id→stderr ablation. | Replaced with clean 3-way. | Accepted |
| 3 | Synthetic padding would be drift. | Replaced with scope decision tree — natural-only. | Accepted at time; **partially revised in v2 R6** after verbatim reviewer text made the evidence standard more permissive. |
| 6 | Under new evidence standard, mutation-in-main is now fine given X/Y protocol. | Accepted retraction of R3 drift warning; moved to two-column design. | Accepted |
| 7 | Model-selection protocol must protect Y and NatErr from tuning; X-dev must be source-provenance-level; contamination-floor protocol vs values. | All three folded into the Methodology subsection. | Accepted |

## Remaining Weaknesses (honest)

1. **NatErr Stage 2 yield dependency**. If < 100 usable, Column B becomes appendix and the paper rests on Column A alone. Principled, not a surprise.
2. **Typed-ID vs structure**. If `DVCR ≈ DVCR − id` on Column A, the causal claim weakens to "structured inference-time compiler verifier". Still publishable, one notch weaker.
3. **Single-compiler main scope**. GCC in appendix only. Reviewers might push for parity.
4. **DrRepair reproducibility**. MACER fallback ready; BIFI third-resort.
5. **Frontier-scale effect compression**. If 70B or frontier closes the gap, framing pivots to "small-model enabler".

## Raw Reviewer Responses

<details>
<summary>Round 1 Review</summary>

See `round-1-review.md` for full verbatim response.

</details>

<details>
<summary>Round 2 Review</summary>

See `round-2-review.md`.

</details>

<details>
<summary>Round 3 Review</summary>

See `round-3-review.md`.

</details>

<details>
<summary>Round 4 Review</summary>

See `round-4-review.md`.

</details>

<details>
<summary>Round 5 Sanity Check</summary>

See `round-5-sanity-check.md`.

</details>

<details>
<summary>Round 6 Review (v2 reopen)</summary>

See `round-6-review.md`.

</details>

<details>
<summary>Round 7 Review (v2 final)</summary>

See `round-7-review.md`.

</details>

## Next Steps

Verdict READY at 9.3. Recommended handoff:

1. **Update `refine-logs/EXPERIMENT_PLAN.md` and `refine-logs/EXPERIMENT_TRACKER.md`** to match the v2 two-column design. This is the next concrete action.
2. **Implement the X-train / X-dev source-provenance carve** for Fuzzlang-Transformer mutations (~1 day of eng).
3. **Integrate DrRepair (or MACER fallback)** into the baseline registry (~2–3 days).
4. **Write `scripts/run_natErr_stage2_llvm.py`** per the LLVM Stage 2 plan from the earlier session (already scaffolded in `scripts/run_natErr_stage2_llvm.py`).
5. **Freeze Model Selection Protocol** — document which Xdev subset + which prompt variants + which hyperparameters were chosen, archive alongside audit manifest.
