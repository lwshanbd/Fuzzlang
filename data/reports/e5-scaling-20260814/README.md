# E5 — More FuzzLang data keeps helping. 2026-08-14

Protocol fixed in advance at
[e5-scaling-protocol](../e5-scaling-protocol/README.md), before any of these
numbers existed.

The same FuzzLang arm trained at three **nested** sizes from the de-vendored
pool, everything else held fixed, evaluated by the pinned patched Clang at
`llvmorg-22.1.8` on the same two 150-instance cohorts as E3.

## The curve

| cohort | 557 | 1,500 | 4,000 | base |
|---|---:|---:|---:|---:|
| **unseen file** | 0.787 | 0.827 | **0.893** | 0.167 |
| | [0.713, 0.853] | [0.760, 0.887] | [0.840, 0.940] | |
| **unseen project** | 0.687 | 0.813 | **0.853** | 0.060 |
| | [0.613, 0.753] | [0.753, 0.873] | [0.793, 0.907] | |
| exact match, unseen file | 0.560 | 0.653 | 0.733 | 0.007 |
| exact match, unseen project | 0.473 | 0.667 | 0.693 | 0.007 |

**It is still rising at 4,000, on both cohorts and on exact match.** The
increments are +0.040 then +0.067 on unseen files and +0.127 then +0.040 on
unseen projects — no step is a plateau, and every step is larger than the
seed-to-seed spread E3 measured for this arm (±0.014 / ±0.030).

Of the three outcomes named in the protocol, this is the first: **E3's matched
comparison is a floor, not a measurement of what FuzzLang data is worth.**

## What this changes about E3

E3 matched every arm to 557 records because DirectEdit — one 31B model call per
record — could not go further. At the budget FuzzLang actually costs:

| cohort | FuzzLang @ 4,000 | DirectEdit @ 557 | intervals |
|---|---:|---:|---|
| unseen file | **0.893** [0.840, 0.940] | 0.642 [0.598, 0.684] | disjoint |
| unseen project | **0.853** [0.793, 0.907] | 0.711 [0.669, 0.751] | disjoint |

E3 reported a **tie** on unseen projects (0.736 vs 0.711). That tie was an
artifact of the shared budget: given the data FuzzLang can produce for free, the
intervals separate cleanly.

## Correction: E3's FuzzLang unseen-project number was flattered by contamination

At the *matched* 557-record budget, the de-vendored arm scores **0.687** on
unseen projects, against E3's **0.736** from the contaminated pool — and against
DirectEdit's clean **0.711**.

| cohort | E3 FuzzLang @557 (contaminated pool) | E5 FuzzLang @557 (de-vendored) | DirectEdit @557 (clean) |
|---|---:|---:|---:|
| unseen file | 0.780 [0.740, 0.818] | 0.787 [0.713, 0.853] | 0.642 [0.598, 0.684] |
| unseen project | 0.736 [0.696, 0.776] | **0.687** [0.613, 0.753] | 0.711 [0.669, 0.751] |

So on a clean pool at a matched budget, FuzzLang does **not** lead DirectEdit on
unseen projects — the intervals overlap in both directions, which is a tie
arrived at honestly rather than a tie that concealed a lead. The unseen-file
result is unaffected (0.787 vs 0.780; the pool change moved nothing there).

This is consistent with the 31 vendored Abseil training records in E3's FuzzLang
arm helping on a cohort that contains 45 Abseil instances. It is not proof: the
E5 arm is a different draw from a different pool, so draw variance is also
available as an explanation, and the two intervals overlap. What is safe to say
is that **E3's unseen-project figure for FuzzLang should not be quoted as
0.736** — the clean measurement at that budget is 0.687, and the argument for
FuzzLang on unseen projects rests on the scaling curve, not on the matched row.

## Why the comparison is about quantity and nothing else

- **Nested tiers.** 557 ⊂ 1,500 ⊂ 4,000, verified in the arm manifest
  (`contains_previous_tier: true`). Ordering is a seeded hash of the record ID:
  deterministic, independent of input order, and uncorrelated with example
  length, so the tiers do not differ in difficulty.
- **De-vendored pool.** Fetched dependencies are excluded, so no Abseil source
  enters training labelled as duckdb or protobuf. This is what makes the
  correction above measurable at all.
- **Everything else fixed.** Same base model and revision, LoRA configuration,
  3 epochs / batch 1 / grad-accum 2 / lr 2e-4 / max-seq-len 1024,
  `window-rewrite` target format, six-dimension leakage guard, cohorts, and
  compiler. Three epochs over more data means more optimizer steps; that is the
  effect being measured, not a confound.

The tiers also widen coverage as they grow — 239 → 319 → 392 distinct
diagnostics and 501 → 1,081 → 1,789 distinct source files — so "more data" here
means more *diverse* data, not more copies. Separating volume from diversity
would need a further experiment holding diagnostic count fixed.

## Limits

**One seed per tier**, so `std` is 0 by construction and the intervals are
bootstrap over instances of a fixed cohort, not over training runs. The
protocol's criterion was that seeds are needed if the steps are smaller than
E3's seed spread; they are not (smallest step 0.040 against ±0.014/±0.030), so
the direction is safe, but the exact heights are not. Three points cannot
distinguish a logarithmic curve from one that saturates later. The pool caps the
top tier at 5,734 records, so any plateau above 4,000 is not observable here.

## Files

- `scaling_curve.csv` — the table above, per cohort and tier
- `scaling-report.json` — with intervals, exact-match rates, and per-step deltas
- `../e5-scaling-protocol/arm-manifest.json` — tier composition and nesting proof

## Reproduce

```bash
# arms (see the protocol for the de-vendored pool construction)
PYTHONPATH=src /p/lustre1/shan4/gemma/venv/bin/python src/repair/run_build_scaling_arms.py \
  --fuzzlang data/gen/experiments/e1-library-replay-v0001/fuzzlang-train-devendored.jsonl \
  --injector-library data/gen/experiments/e1-library-replay-v0001/library.jsonl \
  --eval data/gen/experiments/e3-eval-cohorts-v0001/eval_unseen_tu.jsonl \
  --eval data/gen/experiments/e3-eval-cohorts-v0001/heldout_project.jsonl \
  --tokenizer .artifacts/models/gemma-3-4b-it \
  --model-revision 093f9f388b31de276ce2de164bdc2081324b9767 \
  --sizes 557,1500,4000 --seed 42 --local-files-only \
  --out-dir .artifacts/sft-arms/e5-scaling-seed42

# one job per tier: a single 12h job is pushed out for hours by the pdebug
# reservation, three short ones backfill onto free nodes and run concurrently
for s in 557 1500 4000; do
  flux batch --queue=pdebug --nslots=1 --cores-per-slot=12 --gpus-per-slot=1 \
    --job-name=e5-$s -t 240m \
    --wrap "SIZE=$s bash src/repair/run_tioga_e5_tier.sh"
done

PYTHONPATH=src python3 src/repair/run_scaling_report.py \
  --eval-dir .artifacts/sft-eval/e5-scaling --out-dir data/reports/e5-scaling-20260814
```
