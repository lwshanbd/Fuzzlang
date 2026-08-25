# E9 — Withholding the diagnostic, and the leak it uncovered. 2026-08-25

The repair prompt hands the model the diagnostic name, its message, and the
exact `file:line:col`. The obvious objection is that we measure "follow the
compiler's instructions" rather than repair, so this re-runs the same adapter on
the same cohorts with the prompt withholding that information. Nothing is
retrained.

## The ablation, at face value

FuzzLang-4B trained on 4,000 records, verified fix rate:

| what the prompt reveals | unseen file | unseen project |
|---|---:|---:|
| `full` — name + message + location | 0.893 | 0.853 |
| `no-location` — name + message | 0.900 | 0.840 |
| `none` — nothing but "this does not compile" | **0.913** | 0.833 |

Removing the compiler's answer entirely does not hurt. On unseen files the
score is slightly *higher* without it.

**That result is too good, and chasing it found a defect.**

## The defect: the injected code is labelled

688 of the 9,844 injectors in the released library (7%) emit placeholder
identifiers named `fuzzlang_tmp`, `fuzzlang_tmp_1`, and so on — 664 of them
`append` injectors, which add a self-contained fragment and need names that
cannot collide with the host file:

```c
template <typename... fuzzlang_tmp, typename fuzzlang_tmp_1> struct fuzzlang_tmp_2 {};
```

Those 7% of injectors are prolific, so in the evaluation cohorts:

| cohort | instances whose **source window** contains the literal `fuzzlang` | in the corrected source |
|---|---:|---:|
| unseen file | **61 / 150 (41%)** | 0 |
| unseen project | **69 / 150 (46%)** | 0 |

The marker appears only on the broken side. A model can find the error by
searching for it, without reading a single line of C++.

## How much it inflates the numbers

Splitting every run by whether the instance carries the marker:

| cohort | model | overall | marked | unmarked | gap |
|---|---|---:|---:|---:|---:|
| unseen file | FuzzLang-4B, `full` | 0.893 | 0.951 (61) | **0.854** (89) | +0.097 |
| unseen file | FuzzLang-4B, `none` | 0.913 | 0.951 | **0.888** | +0.063 |
| unseen file | Gemma base | 0.167 | 0.131 | 0.191 | **−0.060** |
| unseen project | FuzzLang-4B, `full` | 0.853 | 0.899 (69) | **0.815** (81) | +0.084 |
| unseen project | FuzzLang-4B, `none` | 0.833 | 0.899 | **0.778** | +0.121 |
| unseen project | Gemma base | 0.060 | 0.015 | 0.099 | **−0.084** |

Two things follow.

**The inflation is about 4 points.** The trustworthy figures are the
unmarked-only columns: **0.854** on unseen files and **0.815** on unseen
projects, against the 0.893 and 0.853 reported so far.

**It is a learned exploit, not an easier subset.** The un-fine-tuned base model
scores *lower* on marked instances (−0.060, −0.084). Marked instances are not
intrinsically simpler; fine-tuning taught the model that a `fuzzlang_*` token is
the thing to revert.

## What survives

The ablation's conclusion holds on the clean subset, which is the version to
report:

| unmarked instances only | unseen file | unseen project |
|---|---:|---:|
| `full` | 0.854 | 0.815 |
| `none` | 0.888 | 0.778 |

Withholding the diagnostic entirely costs at most 3.7 points and on unseen
files costs nothing. **The model is not merely following the compiler's
instructions**, and that claim now rests on instances carrying no giveaway.

## What has to change

1. **Quote the unmarked-only numbers** until the library is fixed. Every
   FuzzLang-4B figure in E3, E5, E6, and E8 is affected by roughly this much;
   they were all measured on these cohorts.
2. **Rename the placeholder identifiers in the generator.** They need to be
   collision-free, not recognisable — a hash of the source file would do both.
   This is a one-line change to injector synthesis plus a library rebuild.
3. **Add a release gate.** No record may contain a token identifying its own
   provenance on the broken side only. This belongs beside the eight gates in
   `dataset_release.py`, and would have caught it at freeze time.

## How it was found

The ablation result was implausible: removing the compiler's answer should cost
*something*. Checking why it did not turned up the marker. Worth recording,
because the defect had been visible for weeks — the degeneracy audit in
`e3-quality-audit-20260812` prints `int fuzzlang_tmp[5] = (int[3]){1, 2, 3};` in
its example diffs — and nobody, including me, registered what it implied.

## Files

- `marker_leak.csv` — every run split by marker presence
