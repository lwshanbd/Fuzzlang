# Review Summary (v1 + v2 cycles)

**Problem**: rewrite the rejected OOPSLA Fuzzlang paper for NeurIPS 2026, extending the idea toward a stronger, more defensible paper that addresses the real OOPSLA reviewer critiques (novelty, experiment rigor, data isolation, ablations, outdated models, missing classical-repair baselines, safety/limitations).
**Initial approach**: "Combine Agent-based code repair (CodeFix), fine-tuning, or both, with compiler cooperation."
**Thread**: `019db833-f01f-7753-a705-e9b1cb416d09`
**Date**: 2026-04-23
**Rounds**: 7 / 8 (2 cycles combined; v1 = R1–R4, R5 = sanity; v2 = R6–R7)
**Final Score**: **9.3 / 10**
**Final Verdict**: **READY**

## Problem Anchor (carried verbatim across all rounds)
See `refine-logs/PROBLEM_ANCHOR.md`. Bottom-line problem held: compiler's structured diagnostic signal is not in the inference loop of any LLM repair pipeline; reported gains collapse once isolation is enforced; fix = put typed diag_id in inference loop. Success condition **revised on 2026-04-23** (v2 cycle) after verbatim OOPSLA reviews were recovered: evidence standard now requires BOTH rigorous mutation-based AND natural-error evaluation (previously natural-only).

---

## v1 Cycle: Rounds 1–4 (+ R5 sanity)

Under paraphrased OOPSLA critique. Converged at natural-only main eval.

| Round | Main Reviewer Concerns | What This Round Simplified / Modernized | Solved? |
|---|---|---|---|
| 1 | Contribution sprawl; GCC/multi-scale/DTFT/multi-search all on critical path; bloated matrix; paper identity not frozen. | Headline locked to one sentence; main table 4 rows + 2 ablations; single 32B; JSON-schema action; parallel-sampling + verifier; GCC/DTFT/multi-scale → appendix. | Yes |
| 2 | `diag_id → stderr` ablation confounded; no multi-diag rule; `span_hash` undefined; "post-cutoff" wording fragile; missing B3 safety. | 3-way verifier-signal ablation; primary-diagnostic-only rule; precise span_hash; calendar-cut + measured contamination floor; B3 appendix-ready; trajectory trim to last 2 turns; HPC column with demote-fallback. | Yes |
| 3 | Latent drift risk: synthetic-pad fallback for sparse naturals; no pre-specified harvesting protocol. | Evaluation-Purity Rule (natural-only); NatErr pipeline; fixed project list; filters + dedup + audit manifest; scope decision tree. HPC fully → appendix. | Yes (but the Evaluation-Purity Rule itself was later revised in v2 after real reviewer text was recovered.) |
| 4 | — | — | READY at 9.2. |
| 5 | Post-READY sanity check on base-model 32B → 7B and calendar-cut 2024-10 → 2025-06. | No regression; READY preserved. | Yes |

---

## v2 Cycle: Rounds 6–7 (this cycle)

Reopened after (a) verbatim OOPSLA reviews recovered in `OOPSLA_REVIEWS.md` and (b) empirical Stage 2 yield from Pine cluster returned 873 raw → 260-540 projected usable, borderline anchor halt territory. MAX_ROUNDS = 3 for this cycle.

| Round | Main Reviewer Concerns | What This Round Simplified / Modernized | Solved? |
|---|---|---|---|
| 6 | R3's "synthetic in eval is drift" warning was based on paraphrased critique; real Reviewer C says "real-world, **not just** injected". Natural-only eval is at halt territory on yield. Need prior-era comparator (Reviewer B). Need stronger-scale calibration (Reviewer B). Need explicit split mechanics (Reviewer A+C). Need limitations/safety section (Reviewer B). | **Two-column main table** (Column A mutation with X/Y project-level holdout + AST-dedup; Column B natural from NatErr). **DrRepair as B_classical**. Scale calibration row (70B + optional frontier). §Methodology explicit on split mechanics. Limitations subsection on `(compile_ok ∧ tests_pass)`. Data + code availability commits. | Yes |
| 7 | Hidden-validity leak: model selection could silently tune on Y or NatErr. | **Model Selection Protocol** subsection: prompts / hyperparameters / schema locked on X-train/X-dev only; Y and NatErr never touched for tuning. X-dev carved at source-provenance level (file/function/commit) before mutation generation. Contamination-floor protocol locked on X-dev, values measured on Y+NatErr. | Yes — READY at 9.3. |

---

## Overall Evolution (across both cycles)

- **Mechanism**: unchanged. DVCR = typed diag_id as first-class observation in an inference-time verifier loop.
- **Paper identity**: stayed single-contribution across both cycles. No sprawl.
- **Evidence standard**: evolved from natural-only (v1 R3-R5) → hybrid mutation-with-rigorous-holdout + naturals (v2 R6-R7). Triggered by verbatim reviewer text showing Reviewer C actually said "**not just** injected" and empirical data showing natural-only would land at halt territory.
- **Baselines**: B0/B1/B2/B3 + DrRepair (added in R6 per Reviewer B).
- **Model scales**: headline 7B + appendix 32B + 70B + optional frontier (per Reviewer B).
- **Ablations**: 3-way verifier-signal + loop-off (unchanged since v1 R2).
- **Rigor protocol**: all the way from anchor-level commitments to the Model Selection Protocol named subsection that prevents silent test-set tuning.

## Final Status

- **Anchor status**: preserved; success condition revised with explicit evidence-standard addendum justified by verbatim reviewer text.
- **Focus status**: tight — one method-paper identity, one dominant contribution, two-column main table with asymmetric roles (A = statistical claim, B = external validity), three causal ablations, one contamination floor.
- **Modernity status**: appropriately frontier-aware — inference-time verifier-grounded search is the right FM-era primitive.
- **Strongest parts of final method**:
  1. Typed 488-class `diag_id` as first-class observation, causally isolable.
  2. Column-A / Column-B design with asymmetric roles (Codex's framing).
  3. Model Selection Protocol published explicitly.
  4. Limitations subsection reports `(compile_ok ∧ tests_pass)` honest gap.
- **Remaining honest risks**:
  - NatErr Stage 2 yield may be < 100 → Column B demotes to appendix; paper survives on Column A.
  - DrRepair may be unmaintainable in 2026 → MACER fallback.
  - 70B / frontier may compress DVCR effect → honest reframing to "small-model enabler".
  - DVCR ≈ DVCR − id → weakens to "structured verifier" rather than "typed ID".
