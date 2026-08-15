# E6 — Is it more data, or more kinds of error? 2026-08-15

E5 showed that more FuzzLang data keeps helping, but its tiers grew record count
and diagnostic coverage together (239 → 392 diagnostics), so it could not say
which one did the work. Breadth is FuzzLang's distinctive claim, so this needed
separating.

Two arms, **same record count, different coverage**:

| arm | records | rendered tokens | diagnostics | source files |
|---|---:|---:|---:|---:|
| narrow | 3,500 | 1,461,808 | **135** | 1,458 |
| broad | 3,500 | 1,526,301 | **427** | 1,720 |

Tokens differ by 4%, coverage by 3.2×. `narrow` fills from the most populous
diagnostics first; `broad` takes one record from every diagnostic before taking
a second from any. Everything else is E5's setup unchanged.

## Result: breadth is not the active ingredient

| cohort | narrow | broad | paired difference | 95% CI |
|---|---:|---:|---:|---|
| unseen file | 0.873 | 0.900 | +0.027 | [−0.020, +0.073] |
| unseen project | 0.800 | 0.833 | +0.033 | [−0.007, +0.080] |

Broad is ahead on both cohorts and on exact match, but **neither interval
excludes zero**, and the two arms agree on 136 and 139 of 150 instances. On this
evidence, tripling diagnostic coverage at a fixed record count buys little or
nothing.

## Why: the skill generalizes across diagnostics

The arms differ enormously in how much of the evaluation they had *seen*:

| cohort | arm | eval instances whose diagnostic was in training | fix rate on those | fix rate on the rest |
|---|---|---:|---:|---:|
| unseen file | narrow | 65% | 0.888 (n=98) | 0.846 (n=52) |
| unseen file | broad | 92% | 0.928 (n=138) | 0.583 (n=12) |
| unseen project | narrow | **28%** | 0.810 (n=42) | **0.796 (n=108)** |
| unseen project | broad | 89% | 0.842 (n=133) | 0.765 (n=17) |

The narrow arm on unseen projects is the clearest case. Its training touched the
diagnostic of only **42 of 150** evaluation instances. On those it scores 0.810;
on the **108 diagnostics it had never seen once**, it scores **0.796**. The gap
is 0.014.

**A model trained on FuzzLang data is not learning a lookup table of per-error
fixes. It is learning to read a compiler diagnostic and repair the code, and
that transfers to error kinds it never saw.** This is consistent with E5: the
curve rises with volume because the model gets more practice at the skill, not
because it accumulates coverage of specific diagnostics.

(Broad's "unseen" cells are small — n=12 and n=17 — so its apparent drop there
is not reliable. The narrow arm's cells are the informative ones.)

## What this means for the paper

It sharpens the breadth claim rather than weakening it, but the claim has to be
stated in the right place.

- **Breadth is a property of the dataset, and that is where it should be
  claimed.** Covering 1,208 of 1,935 diagnostics is what lets the dataset serve
  as a coverage-driven benchmark, expose gaps, and support per-diagnostic
  analysis. None of that depends on breadth improving a fine-tuned model.
- **Breadth is not what makes the fine-tuned model better.** Volume is, and the
  learned skill generalizes across diagnostics. Claiming otherwise would be
  claiming something we measured and did not find.
- **The generalization result is itself worth reporting.** Repairing 108
  diagnostic types never seen in training, at the same rate as the 42 that were,
  is a stronger statement about what the data teaches than a breadth-helps
  result would have been.

## Limits

One seed per arm, so run-to-run variance is not bounded here; the intervals are
bootstrap over instances of a fixed cohort. The comparison holds record count
fixed, not token count (4% apart) and not source-file count (1,458 vs 1,720), so
a small part of broad's edge could be source diversity rather than diagnostic
diversity. A single point at 3,500 records cannot rule out breadth mattering at
much smaller or much larger scales.

## Reproduce

```bash
PY=/p/lustre1/shan4/gemma/venv/bin/python
for mode in broad narrow; do
  PYTHONPATH=src $PY src/repair/run_build_scaling_arms.py \
    --fuzzlang data/gen/releases/fuzzlang-realsource-v1/train.jsonl \
    --injector-library data/gen/experiments/e1-library-replay-v0001/library.jsonl \
    --eval data/gen/experiments/e3-eval-cohorts-v0001/eval_unseen_tu.jsonl \
    --eval data/gen/experiments/e3-eval-cohorts-v0001/heldout_project.jsonl \
    --tokenizer .artifacts/models/gemma-3-4b-it \
    --model-revision 093f9f388b31de276ce2de164bdc2081324b9767 \
    --seed 42 --local-files-only --breadth $mode --count 3500 \
    --out-dir .artifacts/sft-arms/e6-breadth-seed42
  flux batch --queue=pdebug --nslots=1 --cores-per-slot=12 --gpus-per-slot=1 \
    -t 300m --wrap "MODE=$mode bash src/repair/run_tioga_e6_breadth.sh"
done
```

## Files

- `breadth_arms.csv` — arm composition and headline rates
- `paired_contrast.csv` — the paired broad−narrow test
- `seen_vs_unseen_diagnostic.csv` — the generalization table above
