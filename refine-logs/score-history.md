# Score Evolution

| Round | Problem Fidelity | Method Specificity | Contribution Quality | Frontier Leverage | Feasibility | Validation Focus | Venue Readiness | Overall | Verdict | Drift |
|-------|------------------|--------------------|----------------------|-------------------|-------------|------------------|-----------------|---------|---------|-------|
| 1     | 9                | 7                  | 7                    | 9                 | 6           | 5                | 6               | 7.4     | REVISE  | NONE  |
| 2     | 9                | 8                  | 8                    | 9                 | 8           | 8                | 8               | 8.3     | REVISE  | NONE  |
| 3     | 9                | 9                  | 9                    | 9                 | 8           | 8                | 9               | 8.9     | REVISE  | NONE (conditional) |
| 4     | 10               | 9                  | 9                    | 9                 | 9           | 9                | 9               | 9.2     | READY   | NONE  |
| 5*    | 10               | 9                  | 9                    | 9                 | 9           | 9                | 9               | 9.2     | READY   | NONE  |
| 6**   | 10               | 9                  | 9                    | 9                 | 8           | 9                | 9               | 9.1     | READY   | NONE  |
| 7**   | 10               | 9                  | 9                    | 9                 | 8           | 9                | 9               | 9.3     | READY   | NONE  |

*Round 5: post-READY sanity check on feasibility parameter changes. See `round-5-sanity-check.md`.

**Round 6 (v2 cycle): reopened after verbatim OOPSLA reviews recovered + Stage 2 empirical yield. Main change: revised anchor evidence standard from natural-only to hybrid (mutation-with-rigorous-holdout + naturals). Two-column main table. Added DrRepair classical baseline + 70B scale calibration + limitations subsection + explicit split mechanics + data availability commits. R3 drift warning on synthetic-in-eval retracted by reviewer. Only remaining ask: explicit model-selection protocol (addressed in Round 7 refinement).

Threshold for READY: Overall ≥ 9 AND verdict READY AND no drift.

## Notes
- Thread id: `019db833-f01f-7753-a705-e9b1cb416d09`
- Round 1 weighting: PF 15 + MS 25 + CQ 25 + FL 15 + F 10 + VF 5 + VR 5.
