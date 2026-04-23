# Round 5 — Post-READY Parameter Sanity Check

**ThreadId**: `019db833-f01f-7753-a705-e9b1cb416d09`
**Date**: 2026-04-23
**Purpose**: confirm two user-requested feasibility-driven parameter changes do not regress the R4 READY verdict.

## Changes Requested
1. **Base model for main table**: Qwen2.5-Coder-32B → **Qwen2.5-Coder-7B**, 32B demoted to appendix scale-robustness row. Reason: Polaris 4×A100-40GB tooling risk for 32B LoRA; mechanism is not scale-dependent; 7B is a same-scale successor to Fuzzlang v1's Llama-3-8B headline.
2. **Calendar cutoff**: 2024-10-01 → **2025-06-01**. Reason: Qwen2.5-Coder cutoff is ~2024-08 — 2024-10; prior date sat on the border; pushing later gives 8+ month contamination buffer, still leaves 10+ months of commit history through 2026-04-23.

## Reviewer Verdict (verbatim)

1. Change 1 does **not** regress the `READY` verdict. Not drift — core claim is matched-base-model mechanism, not "largest model wins". Main table on 7B is credible if all four main rows + causal ablations use the same 7B, 32B appendix row is retained (defuses "small-model artifact"), and variance/CIs are reported cleanly.
2. Change 2 does **not** regress. Actually cleaner for contamination. Does not touch the anchor. Only risk is NatErr yield, already handled by scope decision tree.
3. **Combined: still READY, still plausibly ≥ 9.** Later cutoff strengthens rigor. Smaller base slightly increases reviewer-risk on scale credibility, but not enough to lose READY as long as 32B appendix remains and causal gaps are clear.

## Guardrails Affirmed (already in FINAL_PROPOSAL)
- 32B appendix scale-robustness row retained.
- All four main rows (B0/B1/B2/DVCR) and all causal ablations use the same 7B.
- 3-seed variance reporting in main table compute budget.
- NatErr scope decision tree unchanged.
- Evaluation-Purity Rule unchanged.
