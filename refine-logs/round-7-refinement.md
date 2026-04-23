# Round 7 Refinement (v2 cycle)

## Problem Anchor
[verbatim from `PROBLEM_ANCHOR.md` including 2026-04-23 evidence-standard addendum]

## Anchor Check
- Bottleneck unchanged.
- Revised method still addresses it. The two-column design is not drift: Column A provides statistical power via rigorously isolated mutations; Column B provides external validity via naturals. Both feed the same mechanism claim.
- Reviewer suggestions rejected as drift: none. All Round-6 feedback was rigor-tightening.

## Simplicity Check
- Dominant contribution unchanged: DVCR inference-time agent with typed diag_id as first-class observation.
- Components removed/merged: none in Round 7.
- Reviewer suggestions rejected as unnecessary complexity: none.
- Why still smallest adequate: Round 7 adds a single protocol sentence, no new component.

## Changes Made

### 1. Model-selection protocol (the only Round-6 remaining ask)
- **Reviewer said**: "all hyperparameter selection, prompt selection, and SFT checkpoint choice must be done on an X-only dev split, never on Y. Otherwise Y becomes a hidden tuning set."
- **Action**: add a one-paragraph **Model Selection Protocol** to the Methodology section. Explicitly names which decisions go through which data.
- **Impact**: closes the last auditable gap Codex flagged. Y-eval and NatErr remain untouched by tuning loops.

### 2. No other changes
- All Column A / Column B design, classical baseline selection, ablations, appendix structure, claims, and risks unchanged from Round 6.

## Revised Proposal (Round 7)

All sections identical to Round 6 except the new Methodology subsection below.

---

### §Methodology — Model Selection Protocol (NEW)

The following decisions are made **only** using data from the training side (Fuzzlang-LLVM mutations of project X = LLVM) or from a held-out development subset carved from X:

- Prompt text for the policy (all three signal modes).
- LoRA rank, alpha, learning rate, and epoch count for the B2 / B3 / DTFT-ablation SFT runs.
- Policy search hyperparameters: T (turn budget), K (parallel proposals per turn), temperature.
- Span window size L, trajectory retention N, dead-end respawn rule.
- DVCR edit-schema (JSON field shape).
- Contamination-floor measurement protocol.

The following data are **never** touched during model-selection or hyperparameter-tuning:

- **Column A eval set (mutations on project set Y = {PostgreSQL, FFmpeg, Qt, Blender})** — final numbers are generated once, at submission time, with hyperparameters locked on X-dev.
- **Column B eval set (NatErr)** — same rule; a single locked configuration is applied once.
- **All appendix eval subsets** (HPC, GCC transfer, 32B/70B calibration): no tuning, single-shot.

Violation of this rule — e.g., peeking at Y-eval to pick between two prompt variants — would silently turn the eval sets into validation sets and invalidate the reported effect size. Model-selection logs are archived alongside the audit manifest so the chain of decisions is auditable post hoc.

This protocol is called out in §Methodology (not buried in the appendix) because Reviewer C's contamination concern in the OOPSLA review is specifically about this kind of silent hidden tuning.

---

### All other sections
Unchanged from Round 6 initial proposal. See `round-6-initial-proposal.md` for:
- Problem Anchor
- Technical Gap
- Method Thesis
- Contribution Focus
- Complexity Budget
- Two-column main table
- Causal ablations
- Claims
- Risks
- Compute & Timeline
