# Review Summary

**Problem**: rewrite the rejected OOPSLA paper *Fuzzlang* for NeurIPS 2026, extending the idea from "fuzz compiler → make training data → fine-tune LLM" to a stronger, more defensible paper that addresses the OOPSLA reviewer critiques (novelty, experiment rigor, data isolation, ablations, outdated models).
**Initial approach**: "Combine Agent-based code repair (CodeFix), fine-tuning, or both, with compiler cooperation."
**Date**: 2026-04-23
**Rounds**: 4 / 5
**Final Score**: **9.2 / 10**
**Final Verdict**: **READY**

## Problem Anchor (carried verbatim across all rounds)
The compiler's diagnostic output is the cheapest, most precise ground-truth signal for code-repair correctness, yet no current LLM repair pipeline closes the loop on it. Static SFT scores collapse under honest data isolation; agent work uses pass/fail or stderr strings rather than the compiler's structured diagnostic vocabulary. Reframe Fuzzlang v1's infrastructure (modified Clang emitting diagnostic IDs) from *dataset generator* into *inference-time verifier*. Success = (1) beats static SFT + stderr-loop under rigorous isolation, (2) gain survives isolation, (3) enables HPC directive-parallel repair.

## Round-by-Round Resolution Log

| Round | Main Reviewer Concerns | What This Round Changed | Solved? | Remaining |
|---|---|---|---|---|
| 1 | Contribution sprawl; multi-scale / multi-budget / DTFT / GCC transfer all on critical path; matrix too large; paper identity not frozen. | Locked headline to one sentence; main table cut to 4 rows + 2 ablations; single base model (Qwen2.5-Coder-32B); JSON-schema edit action; parallel-sampling + verifier-select search; DTFT/GCC/multi-scale → appendix. | Yes | `diag_id → stderr` ablation confounds typed ID with structured interface. |
| 2 | Confounded causal ablation; missing multi-diagnostic rule; `span_hash` undefined; "post-cutoff" wording non-defensible; B3 safety baseline. | 3-way verifier-signal ablation (DVCR / −id / −structure); primary-diagnostic-only rule; precise `span_hash`; cutoff wording separated into calendar cut + measured contamination floor; B3 appendix-ready; trajectory trimmed to last 2 turns; HPC column with demote-fallback. | Yes | Synthetic-pad fallback for sparse naturals was latent drift; eval purity needed a hard rule. |
| 3 | Main table cannot include Fuzzlang-Transformer-generated errors; pre-specify natural-error harvesting + dedup. | **Evaluation-Purity Rule**; NatErr pipeline (S1 git-history + S2 CI logs; S3 `llvm-lit` excluded); fixed project list; filters + dedup + audit manifest; scope decision tree (no synthetic padding, ever); HPC dropped from main → appendix only. | Yes | — |
| 4 | — | — | — | None at proposal level; only residual risk is executional NatErr yield, already handled. |

## Overall Evolution

- **Focus**: from four implicit sub-claims (method + benchmark + protocol + fine-tune) in R0 → one locked headline sentence in R1+ reused verbatim in abstract/conclusion.
- **Concreteness**: from "loop with compiler feedback" in R0 → fully specified state, action schema, span window, span-hash, dead-end detection, K/T parallel search, primary-diagnostic-only rule in R3.
- **Modernity**: started already at 9/10; maintained through four rounds. Structured-output JSON action, parallel proposal + exact-verifier selection are the natural FM-era primitives.
- **Complexity**: multi-scale + multi-budget + multi-search + GCC + DTFT cut to single 32B + matched budget + single search policy + appendix-only GCC/DTFT.
- **Drift**: only one latent drift risk (R2 fallback of supplementing the main split with synthetic errors when naturals are sparse). Caught by R3 reviewer; replaced in R3 with scope decision tree.

## Final Status

- **Anchor status**: preserved across 4 rounds.
- **Focus status**: tight — one method-paper identity, one dominant contribution, one main table, three causal ablations, one contamination floor.
- **Modernity status**: appropriately frontier-aware — inference-time verifier-grounded search is the right FM-era primitive; RL deliberately avoided because inference-time already suffices.
- **Strongest parts of final method**:
  1. Typed 488-class `diag_id` as first-class observation — causally isolable via three-way ablation.
  2. JSON-schema-constrained edit action with ±5-line span window.
  3. Parallel K=4 sampling + exact verifier selection — no beam, no learned scorer.
  4. NatErr pipeline with pre-specified sources, filters, dedup, and scope decision tree → evaluation is audit-proof.
  5. Contamination floor measurement replaces any fragile "post-training-cutoff" claim.
- **Remaining weaknesses / honest risks**:
  - NatErr yield dependency: if < 3000 naturals harvested, scope narrows. Pre-specified and principled, not a surprise.
  - DVCR − id ≈ DVCR possibility: the typed-ID claim could collapse to "structured interface" claim. Anchor still solved; thesis one step weaker; paper still viable.
