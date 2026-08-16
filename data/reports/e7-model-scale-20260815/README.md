# E7 — Is this task already solved by model scale? 2026-08-15

Every fine-tuning result so far uses Gemma-3-4B, whose zero-shot repair rate is
16.7% on unseen files and 6.0% on unseen projects. **A low baseline flatters any
improvement.** If a larger model repairs these errors without fine-tuning, then
"17% → 89%" measures the choice of base model, not what the data teaches.

So it was measured. Gemma-4-31B, no fine-tuning, same cohorts, same prompt, same
window-rewrite parsing, same patched Clang. Only the model changes.

## The result: no, but the headline has to change

| model | fine-tuned | unseen file | exact | unseen project | exact |
|---|---|---:|---:|---:|---:|
| Gemma-3-4B | no | 0.167 | 0.007 | 0.060 | 0.007 |
| **Gemma-4-31B** | **no** | **0.740** | 0.033 | **0.787** | 0.073 |
| 4B + FuzzLang 557 | yes | 0.787 | 0.560 | 0.687 | 0.473 |
| 4B + FuzzLang 1,500 | yes | 0.827 | 0.653 | 0.813 | 0.667 |
| 4B + FuzzLang 4,000 | yes | **0.893** | **0.733** | **0.853** | **0.693** |

**The 31B is a strong zero-shot repairer.** It beats the 557-record fine-tune on
unseen projects (0.787 vs 0.687) and sits between the 1,500 and 4,000 tiers.
Against it, the 6.0% baseline is not the interesting comparison.

**The 4,000-record fine-tune still wins, on both cohorts, paired:**

| cohort | (4B + 4,000) − 31B | 95% CI | wins / losses |
|---|---:|---|---:|
| unseen file | **+0.153** | [+0.087, +0.220] | 27 / 4 |
| unseen project | **+0.067** | [+0.000, +0.133] | 18 / 8 |

The unseen-file interval excludes zero. The unseen-project interval touches it,
so that one is a lead, not a proven one.

## What must be said differently from now on

**Retire "16.7% → 89%".** It is arithmetically true and rhetorically misleading:
it compares against a base model that no one would deploy for this task. The
claim the evidence supports is:

> A 4B model fine-tuned on 4,000 FuzzLang records outperforms a model eight
> times its size that has not been fine-tuned — +0.153 on unseen files and
> +0.067 on unseen projects.

That is an efficiency claim, and it is stronger than the one it replaces,
because the comparison is against something worth comparing to.

## The exact-match gap is real but must be reported carefully

The 31B reproduces the reference repair on 3.3% / 7.3% of instances; the
fine-tuned 4B on 73.3% / 69.3%. That is a twenty-fold difference and it is not
noise.

**It is not evidence that the 31B is cheating.** A degeneracy audit of its
outputs found delete-to-compile behaviour in **1.8% and 0.8%** of its verified
fixes — *lower* than the fine-tuned model's 6.6% and 3.6%. Its median accepted
edit is 34 and 27.5 characters against the reference's ~46 and ~43. The 31B is
producing genuine, compact, alternative repairs; it simply does not pick the
developer's.

**And it is partly confounded.** The fine-tuned model was trained on records
built by the same injector library that produced the evaluation instances, so
some of its exact-match advantage is distribution match rather than repair
quality. Verified fix rate is the metric that survives this objection; exact
match should be reported as *agreement with the reference repair*, with the
confound stated, not as a quality score.

## Fairness caveat: the output budget favours the fine-tuned models

Both were evaluated at 512 new tokens. The 31B is verbose — median response
1,469 characters against the fine-tuned model's 534 — and **11 of its 12 parse
failures on the unseen-file cohort are truncations**, not format errors: it
emits well-formed `{"corrected_window": ...}` JSON that runs out of budget. On
parsed instances only, its unseen-file rate is 0.804 rather than 0.740.

512 was chosen when every model under test had been fine-tuned to be terse. A
re-run at 1,024 tokens is outstanding; it will raise the 31B's numbers somewhat
and cannot change the direction on the unseen-file cohort (+0.153 with a lower
bound of +0.087).

## A note on how this was run, because it was run badly first

The first attempt loaded the 31B in-process with `device_map="auto"` and
generated one instance at a time. That is layer-sharded pipeline parallelism at
batch size 1: **eight GPUs allocated, roughly one GPU's throughput**, 3h17m per
cohort, and a job that hit its time limit. The inefficiency was noticed and then
paid for with a longer reservation instead of being fixed.

`run_adapter_eval.py` now takes `--backend vllm --base-url`, driving an
already-served model over its OpenAI-compatible API so tensor parallelism uses
the whole node. Comparability is protected by construction: the messages come
from the same builder as the local path, decoding stays greedy, and only the
execution changes. Tests assert exactly that.

## Files

- `model_comparison.csv` — the table above
- `paired_vs_31b.csv` — instance-paired contrast against the 31B
- `degeneracy.csv` — the audit showing the 31B is not delete-to-compiling
