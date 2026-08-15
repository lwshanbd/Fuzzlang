# E3 — Does FuzzLang data make a repair model better? 2026-08-11

Matched-budget SFT of `google/gemma-3-4b-it` on three construction arms, plus
the un-finetuned base, evaluated by the pinned patched Clang at
`llvmorg-22.1.8` on two held-out cohorts.

## Setup

- **Arms** (matched exactly): 557 records and **260,751 rendered tokens each**,
  relative gap 0.0, same epochs / batch size / gradient accumulation, so the
  optimizer-update count matches too. Zero truncation (longest example 974 of a
  1,024 budget). Representation: `window-rewrite`.
- **Seeds**: 42, 1337, 20260808 for every SFT arm.
- **Cohorts** (150 instances each, stratified by project × language, seed
  20260809): `eval_unseen_tu` — files reserved inside the 9 training projects;
  `heldout_project` — Abseil, FFmpeg, leveldb, json-c, which contributed no
  training record.
- **Leakage**: zero overlap between every training arm and every cohort on
  record ID, source TU, corrected source, erroneous source, whitespace-normalised
  corrected source, and the paired-source hash.

## Result

| cohort | arm | verified fix rate | ±std | 95% CI | exact match | excl. Abseil |
|---|---|---:|---:|---|---:|---:|
| unseen file | **FuzzLang-SFT** | **0.780** | 0.014 | [0.740, 0.818] | **0.538** | 0.780 |
| unseen file | DirectEdit-SFT | 0.642 | 0.026 | [0.598, 0.684] | 0.378 | 0.642 |
| unseen file | Gemma Base | 0.167 | — | [0.107, 0.227] | 0.007 | 0.167 |
| unseen file | Mechanical-SFT | 0.020 | 0.009 | [0.009, 0.033] | 0.009 | 0.020 |
| unseen project | **FuzzLang-SFT** | **0.736** | 0.030 | [0.696, 0.776] | **0.542** | **0.737** |
| unseen project | DirectEdit-SFT | 0.711 | 0.021 | [0.669, 0.751] | 0.416 | 0.638 |
| unseen project | Gemma Base | 0.060 | — | [0.027, 0.100] | 0.007 | 0.067 |
| unseen project | Mechanical-SFT | 0.027 | 0.011 | [0.013, 0.042] | 0.000 | 0.035 |

**Headline.** Fine-tuning on FuzzLang data lifts verified repair from **16.7% to
78.0%** on unseen files, and from **6.0% to 73.6%** on projects that
contributed nothing to training — a transfer that also crosses a language
boundary, since FFmpeg and json-c are C while the training data is mostly C++.

**FuzzLang versus DirectEdit.** On unseen files, 0.780 vs 0.642 with
non-overlapping intervals. On unseen projects the intervals overlap (0.736 vs
0.711) — a tie. Exact match favours FuzzLang in both cohorts (0.538 vs 0.378;
0.542 vs 0.416): its outputs more often reproduce the reference repair rather
than merely compiling.

> **Correction (2026-08-14): do not quote 0.736.** Rebuilding this arm from the
> de-vendored pool at the same 557-record budget gives **0.687** on unseen
> projects — below DirectEdit's clean 0.711, with overlapping intervals. The
> unseen-file figure is unaffected (0.787 vs 0.780). The 0.736 above is
> consistent with the 31 vendored Abseil training records helping on a cohort
> containing 45 Abseil instances, though draw variance is also available as an
> explanation. FuzzLang's case on unseen projects rests on the scaling curve in
> [e5-scaling-20260814](../e5-scaling-20260814/README.md), not on this row.

**The matched budget is a floor, not a measurement.** 557 records is what
DirectEdit could afford at one 31B call per record; FuzzLang costs nothing per
record beyond compilation. At 4,000 records it reaches **0.893** on unseen files
and **0.853** on unseen projects, both with intervals disjoint from DirectEdit's,
and is still rising. The unseen-project tie above is an artifact of the shared
budget.

> **Correction (2026-08-13).** This section previously read the `excl. Abseil`
> column as the gap "widening to 0.737 vs 0.638" once contamination was removed.
> That reading is withdrawn. Dropping Abseil also drops 45 instances whose
> diagnostics are almost all Abseil-exclusive, so it changes the diagnostic mix
> at the same time and is not the same comparison minus contamination. See
> [e3-project-confound-20260813](../e3-project-confound-20260813/README.md).
> The unseen-project claim rests on the full-cohort tie above.

**Mechanical-SFT is worse than no fine-tuning at all** (0.020 / 0.027 versus
0.167 / 0.060), losing 25 of 26 decided pairs against the base model. It also
has the *lowest* training loss of the three arms (0.018 vs 0.030 FuzzLang and
0.049 DirectEdit): mechanical mutations are the most regular and therefore the
easiest to fit. Training loss is not evidence of repair quality, and this arm is
the control that shows the gains are not simply "more tokens".

## Caveat: Abseil is contaminated for two arms

duckdb and protobuf vendor Abseil into their build trees under
`build/_deps/absl-src/`. The clean-source gate excluded test paths but not
fetched dependencies, so Abseil source entered training labelled as duckdb and
protobuf — while Abseil was a held-out evaluation project. Affected: FuzzLang 31
records over 24 vendored Abseil files, Mechanical 26 over 23; **DirectEdit is
clean**. Content hashes did not catch it because the vendored revision differs
from the standalone checkout.

Contamination did *not* explain the Abseil results: the clean DirectEdit arm
scored **highest** there (0.881).

**That is now explained, and it is not a project effect at all.** In this cohort
61 of 68 diagnostics occur in exactly one project, so the per-project and
per-diagnostic breakdowns are the same table. Reweighting each diagnostic's
pooled rate by a project's mix predicts every per-project rate to within a mean
absolute residual of **0.010**; on the 7 diagnostics Abseil shares with leveldb —
the only place the two factors separate — the difference is +0.113 [−0.210,
+0.418] for DirectEdit and −0.188 [−0.503, +0.137] for FuzzLang, with 11 and 15
instances. See
[e3-project-confound-20260813](../e3-project-confound-20260813/README.md).

The `excl. Abseil` column is therefore **not** the trustworthy unseen-project
number: excluding Abseil is justified as contamination control but simultaneously
changes the diagnostic mix. Quote the full-cohort figures, and do not read the
per-project table as a project effect in either direction.

`is_vendored_path()` now rejects `_deps/`, `third_party/`, `vendor/`,
`contrib/`, `deps/`, `CMakeFiles/`, and generated unity-build stubs at three
points in the clean-source gate, so no future pool can carry this. Applying it
to the current pools would remove 507 of 1,196 sources — 352 of duckdb's 391 and
153 of protobuf's 464 — which also means **E1's per-project attribution
overstates duckdb and protobuf** and must be recomputed.

## Files

- `arm_table.csv` — the table above, per cohort and arm.
- `per_project_language.csv` — fix rate per project and per language, per arm.
- `paired_differences.csv` — instance-level paired differences against Base,
  Mechanical, and DirectEdit, with bootstrap intervals and win/loss/tie counts.

## Behaviour audit

Compile-clean is not behavioural correctness, so every archived generation was
re-read for delete-to-compile degeneracy — see
[e3-quality-audit-20260812](../e3-quality-audit-20260812/README.md).

**93–96% of FuzzLang's verified fixes survive.** Non-degenerate rates are 0.729
(unseen file) and 0.709 (unseen project) against DirectEdit's 0.598 and 0.676;
the ranking is unchanged and the unseen-project margin widens. There are zero
large deletions and zero empty repairs across all 20 configurations.

The audit also explains the Mechanical control: its reference repair is **one
character wide at every quartile**, so the loss-minimising policy is the
identity map, and **67.6% of its predictions are byte-identical to their
input**. Its low training loss and its 2% repair rate are the same fact.

Degeneracy tracks the injector operation, not the generator: `insert`-built
tasks degenerate at 1.3–2.2% for both arms, `replace`-built tasks at 13–32% for
both. A `replace` overwrites the original statement, so its inverse repair task
is genuinely under-determined.

## Limits

Three seeds bound run-to-run variance, not corpus variance; the bootstrap
intervals are over instances of one fixed cohort. Training arms are 557 records
— the size the most expensive arm (DirectEdit) could reach, not the size
FuzzLang could supply (5,666 eligible). The behaviour audit bounds the obvious
failure mode (delete-to-compile) with static edit-shape signals; it does not
prove semantic equivalence, which would need the projects' test suites.
