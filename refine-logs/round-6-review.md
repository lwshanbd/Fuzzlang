# Round 6 Review (Codex / gpt-5.4, xhigh, same thread 019db833)

**Date**: 2026-04-23
**Context**: Reopened after verbatim OOPSLA reviews recovered and Stage 2 empirical yield came in. Round-3 drift warning ("supplementing with synthetic is drift") based on paraphrased critique; revised anchor evidence standard now requires both mutation-with-rigorous-holdout AND naturals.

## Parsed Scores

| Dimension | R4 (prior cycle) | **R6** |
|---|---|---|
| Problem Fidelity | 10 | **10** |
| Method Specificity | 9 | **9** |
| Contribution Quality | 9 | **9** |
| Frontier Leverage | 9 | **9** |
| Feasibility | 9 | **8** (DrRepair reproducibility risk noted) |
| Validation Focus | 9 | **9** |
| Venue Readiness | 9 | **9** |
| **Overall (weighted)** | 9.2 | **9.1** |
| Verdict | READY | **READY** |
| Drift | NONE | **NONE** |

## Reviewer's Assessment

- **Column A mutation-with-project-holdout is sufficient rigor.** X/Y disjoint + AST-hash dedup is not cosmetic; it is the right fix for Reviewer C's same-codebase objection.
- **Mutation in main eval is now fine.** The Round-3 drift warning is retracted given the revised anchor: "rigorously isolated mutations for power + naturals for external validity" is the correct framing.
- **Two-column design is not overbuilt** if asymmetric roles are kept: Column A = primary statistical claim; Column B = real-world generalization check at whatever honest Stage 2 scale yields.
- **DrRepair is the right classical baseline** — old but still the cleanest compile-error-repair comparator. MACER as fallback if unmaintainable; BIFI less aligned; LaMirage too domain-shifted.

## Remaining Action Item (only one)

**Model-selection protocol**. Add one sentence to the methodology: *prompts, SFT checkpoints, policy hyperparameters, and search knobs are frozen using ONLY training-side or X-side development data — never using NatErr and never using Y-eval.* Without this explicit commitment, Y silently becomes a tuning set over the course of the experimental sweep. This is the only remaining gap.

## Drift Warning
**NONE.**

## Executional risks called out (not blockers)
1. NatErr yield < 100 → Column B becomes appendix; paper leans on Column A. Already handled.
2. DrRepair reproducibility → MACER fallback ready.
3. 70B / frontier appendix must stay single-row, not a parallel paper.

---

<details>
<summary>Raw verbatim review</summary>

**Scores**
1. Problem Fidelity: `10/10`
2. Method Specificity: `9/10`
3. Contribution Quality: `9/10`
4. Frontier Leverage: `9/10`
5. Feasibility: `8/10`
6. Validation Focus: `9/10`
7. Venue Readiness: `9/10`

**Overall:** `9.1/10`
**Verdict:** `READY`
**Drift Warning:** `NONE`

**Q1. Does Column A address Reviewer C's same-codebase objection?**
Yes. `train on X / eval on disjoint Y + AST-hash dedup across X↔Y` is a real fix, not cosmetic. It is much stronger than the old LLVM-only 80/20 split. The one thing to lock down is this: all hyperparameter selection, prompt selection, and SFT checkpoint choice must be done on an `X-only dev split`, never on `Y`. Otherwise Y becomes a hidden tuning set. That is the only missing rigor detail I still care about.

**Q2. Is DrRepair too old? Substitute?**
DrRepair is old, but not too old for this purpose. It is still the cleanest "classical compile-error repair" comparator and directly answers Reviewer B's objection. I would keep `DrRepair` as `B_classical`. If it proves unmaintainable, `MACER` is the better substitute. `BIFI` is less aligned, and `LaMirage` is too domain-shifted to matter for C/C++ compiler repair.

**Q3. Is mutation in the main eval now fine, or still drift?**
It is now fine. My earlier drift warning was based on the wrong evidence standard. Under the revised anchor, the right story is: `rigorously isolated mutations for power + naturals for external validity`. That is not drift. It would become drift only if the natural column disappeared and the paper reverted to synthetic-only evidence.

**Q4. Is the two-column design overbuilt?**
No, not if you keep the roles asymmetric:
- `Column A` is the primary statistical claim.
- `Column B` is the real-world generalization check at whatever honest scale you can reproduce.

That is real evidence, not contribution sprawl. The mistake would be to write the paper as if both columns carry equal inferential weight. They do not. Column A proves the mechanism cleanly; Column B checks that it is not an artifact of the mutation regime.

**What still blocks READY?**
No conceptual blocker remains. The remaining risks are executional:
- `NatErr` may be small. You already handled that correctly.
- `DrRepair` may be painful to reproduce. Have `MACER` ready as fallback.
- Do not let the stronger-model appendix become a second paper. One `70B` calibration row is enough.

**Anything still not addressed from the verbatim OOPSLA reviews?**
Almost everything material is now covered. The only detail I would still make explicit in the paper is:
- a short `model-selection protocol` sentence stating that prompts/checkpoints/hyperparameters are frozen using only training-side or X-side development data, never NatErr and never Y-eval.

With that addition, this remains `READY`.

</details>
