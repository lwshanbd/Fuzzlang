# E5 — Does more FuzzLang data keep helping? Protocol, 2026-08-13

**Status: submitted, results pending.** This file fixes the protocol before the
numbers exist, so the analysis cannot be chosen after seeing them.

## Why this experiment

[E3](../e3-sft-value-20260811/README.md) matched every construction arm to
**557 records and 260,751 rendered tokens**, because that is the size the most
expensive arm could reach — DirectEdit costs one 31B model call per record.
FuzzLang costs nothing per record beyond compilation, and the de-vendored
training pool holds **5,734 eligible records**, an order of magnitude more.

So E3's margin over DirectEdit is a **lower bound**: it measures FuzzLang data
at a budget chosen by its competitor. E5 asks the question that budget hid — if
you are willing to spend what FuzzLang actually costs, does the extra data keep
buying repair accuracy, or does it saturate?

## Design

**Arms.** The *same* arm at three nested sizes, seed 42:

| tier | records | rendered tokens | distinct diagnostics | distinct source TUs |
|---:|---:|---:|---:|---:|
| 557 | 557 | 244,700 | 239 | 501 |
| 1,500 | 1,500 | 650,216 | 319 | 1,081 |
| 4,000 | 4,000 | 1,719,461 | 392 | 1,789 |

**Nested by construction.** The 557 tier is a prefix of the 1,500 tier, which is
a prefix of the 4,000 tier (`contains_previous_tier: true` in the arm manifest).
Ordering is a seeded hash of the record ID — deterministic, independent of input
order, and uncorrelated with example length, so the tiers do not differ in
difficulty. Without nesting, a difference between tiers could be *which* records
were drawn rather than *how many*.

**Pool is de-vendored.** Unlike E3, the source pool excludes fetched
dependencies (`is_vendored_path`), so Abseil source cannot enter training
labelled as duckdb or protobuf. 1,728 of 7,470 train-split records are dropped
for this reason. The Abseil contamination that qualified E3's unseen-project
column therefore does not apply here.

**Everything else is held fixed.** Same base model and revision
(`google/gemma-3-4b-it` @ `093f9f38`), same LoRA configuration, same 3 epochs /
batch 1 / grad-accum 2 / lr 2e-4 / max-seq-len 1024, same `window-rewrite`
target format, same leakage guard against both cohorts on six dimensions, same
150-instance cohorts (`eval_unseen_tu`, `heldout_project`), same patched Clang
at `llvmorg-22.1.8`.

Three epochs over more data means more optimizer steps. That is deliberate and
is the effect under measurement — "more data" in practice means more updates.
It is *not* the confound E3 controlled for; E3 controlled for token count across
*different* construction methods, which is a different question.

## What each outcome would mean

- **Still rising at 4,000** — FuzzLang's advantage over DirectEdit in E3 is
  understated, and the correct statement is that the matched comparison is a
  floor.
- **Saturating between 1,500 and 4,000** — 557 records were already near the
  useful limit for this model and task, which would make E3's matched budget a
  fair comparison rather than a handicap, and would locate the bottleneck in
  model capacity or task format rather than data volume.
- **Falling** — over-fitting to the injector distribution; would need a held-out
  diagnostic-family analysis to interpret.

All three are publishable. The claim to avoid is asserting the first without
measuring.

## Reproduce

```bash
# 1. de-vendored FuzzLang training pool
PYTHONPATH=src python3 -c "
import json, glob, sys; sys.path.insert(0,'src')
from gen.realcorpus.corpus import is_vendored_path
with open('data/gen/experiments/e1-library-replay-v0001/fuzzlang-train-devendored.jsonl','w') as out:
    for p in sorted(glob.glob('data/gen/experiments/e1-library-replay-v0001/*-train/records.jsonl')):
        if 'cap5-fileorder' in p: continue
        for l in open(p):
            d=(json.loads(l).get('provenance') or {}).get('detail') or {}
            if not is_vendored_path(d.get('source_path') or ''): out.write(l)"

# 2. nested arms
PYTHONPATH=src /p/lustre1/shan4/gemma/venv/bin/python src/repair/run_build_scaling_arms.py \
  --fuzzlang data/gen/experiments/e1-library-replay-v0001/fuzzlang-train-devendored.jsonl \
  --injector-library data/gen/experiments/e1-library-replay-v0001/library.jsonl \
  --eval data/gen/experiments/e3-eval-cohorts-v0001/eval_unseen_tu.jsonl \
  --eval data/gen/experiments/e3-eval-cohorts-v0001/heldout_project.jsonl \
  --tokenizer .artifacts/models/gemma-3-4b-it \
  --model-revision 093f9f388b31de276ce2de164bdc2081324b9767 \
  --sizes 557,1500,4000 --seed 42 --local-files-only \
  --out-dir .artifacts/sft-arms/e5-scaling-seed42

# 3. train, evaluate, report -- one allocation
flux batch --queue=pdebug --nslots=1 --cores-per-slot=12 --gpus-per-slot=1 \
  --job-name=e5-all -t 700m --wrap bash src/repair/run_tioga_e5_all.sh
```

## Limits, stated in advance

One seed per tier. Three seeds bounded run-to-run variance in E3 and should be
added here if the curve's steps are smaller than E3's seed spread (±0.014 to
±0.030). Three points cannot distinguish a logarithmic curve from a saturating
one; they can only show direction and rough magnitude. The pool caps the top
tier at 5,734, so a plateau above that is not observable from this run.
