# Round 7 Review (Codex / gpt-5.4, xhigh, same thread 019db833)

**Date**: 2026-04-23
**Context**: Round 7 refinement added a Model Selection Protocol subsection to §Methodology, addressing the only remaining Round-6 ask.

## Parsed Scores

| Dimension | R6 | **R7** |
|---|---|---|
| Problem Fidelity | 10 | **10** |
| Method Specificity | 9 | **9** |
| Contribution Quality | 9 | **9** |
| Frontier Leverage | 9 | **9** |
| Feasibility | 8 | **8** (DrRepair reproducibility risk persists; executional not conceptual) |
| Validation Focus | 9 | **9** |
| Venue Readiness | 9 | **9** |
| **Overall (weighted)** | 9.1 | **9.3** (estimated; Codex said "9.2+") |
| Verdict | READY | **READY** |
| Drift | NONE | **NONE** |

## Verbatim judgment
> "This closes the remaining ask. Quick re-score: no meaningful change to the Round 6 verdict except a small improvement in methodological rigor. Overall still READY, still around 9.2+."

## Two small wording refinements Codex still suggests

These are wording-level, not design-level. Folding into the final proposal:

### Refinement A: X-dev carved at source-provenance level
> "Say that X-dev is carved **before mutation generation / expansion at the source provenance level** (for example by file, function, or commit), so mutations from the same underlying function do not land in both X-train and X-dev."

Apply: methodology subsection on model selection now explicitly states X-dev is a source-provenance-level holdout (by file / function / commit) on the underlying LLVM source — NOT a random 80/20 on the post-mutation dataset. Mutations from the same function cannot bridge X-train ↔ X-dev.

### Refinement B: contamination-floor protocol vs values
> "Keep 'contamination-floor measurement protocol' under 'protocol decisions locked on X-dev,' but make clear the **actual floor values** are still measured on Y-eval and NatErr, not on X-dev."

Apply: separate "how we measure the contamination floor" (procedure, locked on X-dev) from "what the floor values are" (measured on Y-eval and NatErr at submission time, no tuning).

## Drift Warning
**NONE.**

---

<details>
<summary>Raw verbatim review</summary>

This closes the remaining ask.

Quick re-score: no meaningful change to the Round 6 verdict except a small improvement in methodological rigor. Overall still `READY`, still around `9.2+`.

What changed:
- It removes the last hidden-validity concern: `Y-eval` and `NatErr` are now explicitly protected from prompt / hyperparameter / schema selection.
- It makes the paper easier to defend against the obvious reviewer question, "did you tune on the test sets?"

Does it leak or double-count `X`'s role?
- No leakage into final evaluation. Using `X-train` for training and `X-dev` for selection is standard and does not regress the design.
- It is not problematic that `X` plays both "source domain for training" and "source domain for dev," because the final claims are on `Y` and `NatErr`, not on `X`.

One refinement I would still make in the text:
- Say that `X-dev` is carved **before mutation generation / expansion at the source provenance level** (for example by file, function, or commit), so mutations from the same underlying function do not land in both `X-train` and `X-dev`.

One wording cleanup:
- Keep "contamination-floor measurement protocol" under "protocol decisions locked on X-dev," but make clear the **actual floor values** are still measured on `Y-eval` and `NatErr`, not on `X-dev`.

So: yes, this closes the remaining issue; no new blocker; verdict remains `READY`.

</details>
