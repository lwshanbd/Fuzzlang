# The Abseil anomaly is not an anomaly — 2026-08-13

[E3](../e3-sft-value-20260811/README.md) left one result unexplained: on the
held-out cohort the **clean** DirectEdit arm scored 0.881 on Abseil against
0.61–0.65 on the other three projects, so contamination could not be the cause.

It is not a project effect. **The per-project breakdown and the per-diagnostic
breakdown are the same table.**

## The two factors barely separate

| cohort | instances | projects | diagnostics | project-exclusive diagnostics | instances whose diagnostic occurs in >1 project | median instances per diagnostic |
|---|---:|---:|---:|---:|---:|---:|
| `heldout_project` | 150 | 4 | 68 | **61** | 26 (17%) | 1 |
| `eval_unseen_tu` | 150 | 9 | 61 | 42 | 94 (63%) | 1 |

In the held-out cohort, 61 of 68 diagnostics occur in exactly one project, and
the median diagnostic contributes a single instance. FFmpeg and json-c share no
diagnostic with any other project at all.

The cause is structural, not a sampling mistake: the cohort was stratified by
project × language, and an Injector targets one diagnostic and matches one
codebase's idioms, so diagnostics cluster by project on their own. json-c is the
clearest case — 13 of its 17 instances are `err_c11_noreturn_misplaced`, so
FuzzLang's 0.882 there is one diagnostic, not one project.

## Diagnostic mix predicts every project

Reweighting each diagnostic's **pooled** rate by how much of a project it makes
up reproduces the observed per-project rates:

| arm | project | observed | predicted from diagnostic mix | residual |
|---|---|---:|---:|---:|
| DirectEdit | abseil | 0.881 | 0.861 | **+0.021** |
| DirectEdit | leveldb | 0.636 | 0.658 | −0.021 |
| FuzzLang | abseil | 0.733 | 0.752 | −0.018 |
| FuzzLang | leveldb | 0.720 | 0.701 | +0.019 |
| DirectEdit / FuzzLang | ffmpeg, json-c | — | — | 0.000 *(vacuous)* |

Mean |residual| is **0.010**. The ffmpeg and json-c zeros carry no information:
their diagnostics are project-exclusive, so the pooled rate *is* the project
rate and the prediction is circular. Abseil and leveldb are the only projects
where the question can be asked, and there the answer is that essentially
nothing is left over for the project.

## The one place the factors do separate says nothing either

Seven diagnostics occur in both Abseil and leveldb — the entire basis for
separating project from diagnostic in this cohort. Restricting to them, and
counting **instances** rather than seed-copies:

| arm | abseil (n=11) | leveldb (n=15) | difference | 95% CI |
|---|---:|---:|---:|---|
| DirectEdit | 0.758 | 0.644 | +0.113 | [−0.210, +0.418] |
| FuzzLang | 0.545 | 0.733 | −0.188 | [−0.503, +0.137] |

Both intervals straddle zero. With 11 and 15 instances the design cannot resolve
a difference of this size in either direction.

## Correction to E3

E3's `excl. Abseil` column reported FuzzLang 0.737 versus DirectEdit 0.638 on
the unseen-project cohort and described the gap as *widening* once contamination
was removed. Excluding Abseil remains justified — 31 FuzzLang and 26 Mechanical
training records came from vendored Abseil source — but the resulting number is
**not** the same comparison minus contamination. Dropping Abseil drops 45
instances whose diagnostics are almost all Abseil-exclusive, so it changes the
diagnostic mix at the same time. The widening is confounded with that change and
should not be read as a cleaner estimate of the same quantity.

**What still stands:** the aggregate unseen-project rates over the full cohort
(FuzzLang 0.736, DirectEdit 0.711, intervals overlapping — a tie), and the
unseen-file result, which is aggregate and unaffected. **What should be
withdrawn:** any reading of the per-project table as a project effect, in either
direction, and the claim that excluding Abseil sharpens the comparison.

## What a project effect would require

A cohort stratified by **diagnostic × project**, so each diagnostic appears in
several projects, with enough instances per cell to separate the two. The
current pool can support this only for diagnostics the library reaches in more
than one codebase — 150 of them cross a project boundary in E1, so such a cohort
is constructible. It has not been built, and until it is, FuzzLang's transfer
claim should rest on the aggregate held-out-project number alone.

## Reproduce

```bash
PYTHONPATH=src python3 src/repair/run_confound_report.py \
  --eval-dir .artifacts/sft-eval/e3-v0002 \
  --cohort heldout_project=data/gen/experiments/e3-eval-cohorts-v0001/heldout_project.jsonl \
  --cohort eval_unseen_tu=data/gen/experiments/e3-eval-cohorts-v0001/eval_unseen_tu.jsonl \
  --out-dir data/reports/e3-project-confound-20260813
```

## Files

- `project_diagnostic_overlap.csv` — separability of the two factors per cohort
- `project_rates_adjusted.csv` — observed, predicted-from-mix, and residual for
  every arm and project in both cohorts
- `shared_diagnostic_contrast.csv` — the 7-diagnostic paired test above
