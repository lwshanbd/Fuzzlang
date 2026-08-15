# E3 behaviour audit — is a "verified fix" actually a repair? 2026-08-12

`verified fix` in [e3-sft-value-20260811](../e3-sft-value-20260811/README.md)
means the patched Clang at `llvmorg-22.1.8` accepted the repaired translation
unit. That is a necessary condition, not a sufficient one: deleting the
offending line also compiles. This audit re-reads every archived generation
from that run and asks what the model actually wrote.

No model and no compiler are involved — the signals are static diffs between
the input window, the prediction, and the reference repair
(`repair/eval/edit_quality.py`), so the whole audit reruns in under a minute.

## Headline: 93–96% of FuzzLang's verified fixes survive the audit

| cohort | arm | verified fix | **non-degenerate fix** | degenerate share |
|---|---|---:|---:|---:|
| unseen file | **FuzzLang-SFT** | 0.780 | **0.729** | 6.6% |
| unseen file | DirectEdit-SFT | 0.642 | 0.598 | 6.9% |
| unseen file | Gemma Base | 0.167 | 0.153 | 8.0% |
| unseen file | Mechanical-SFT | 0.020 | 0.020 | 0.0% |
| unseen project | **FuzzLang-SFT** | 0.736 | **0.709** | 3.6% |
| unseen project | DirectEdit-SFT | 0.711 | 0.676 | 5.0% |
| unseen project | Gemma Base | 0.060 | 0.060 | 0.0% |
| unseen project | Mechanical-SFT | 0.027 | 0.027 | 0.0% |

Every conclusion of E3 survives: the ranking is unchanged and FuzzLang's margin
over DirectEdit *widens* slightly on unseen projects (0.709 vs 0.676) because
DirectEdit degenerates more often there.

**There is not a single large deletion or empty repair in the entire run.** The
only degeneracy mode that fires in quantity is `pure_line_deletion` — removing
a line without writing a replacement — plus 5 cases of `excessive_edit` across
all 20 configurations.

FuzzLang also does not win by editing less: its median accepted edit is 56
diff characters on unseen files against DirectEdit's 44, with the reference
repair at 46.

## Degeneracy is a property of the task, not of the method

Splitting by the injector operation that built each evaluation instance:

| cohort | arm | operation | fixes | degenerate |
|---|---|---|---:|---:|
| unseen file | FuzzLang | `insert` | 291 | **1.4%** |
| unseen file | FuzzLang | `replace` | 60 | **31.7%** |
| unseen file | DirectEdit | `insert` | 236 | 1.3% |
| unseen file | DirectEdit | `replace` | 53 | 32.1% |
| unseen project | FuzzLang | `insert` | 286 | 2.1% |
| unseen project | FuzzLang | `replace` | 45 | 13.3% |
| unseen project | DirectEdit | `insert` | 274 | 2.2% |
| unseen project | DirectEdit | `replace` | 46 | 21.7% |

An `insert` injection leaves the original statement in the window, so the
repair is determined and both arms are essentially clean. A `replace` injection
**overwrites** the original statement, and the overwritten text appears nowhere
in the model's context — so the task is genuinely under-determined and deleting
the injected line is a defensible compiling answer. Example
(`library-replay-389e9bf6ed3c`, `err_array_init_different_type`): the reference
restores `s->high_water = 0;`, which is unrecoverable from the window; the
model deletes the line instead.

The two arms degenerate at the *same* rate on `replace` (31.7% vs 32.1%) and
the same rate on `insert` (1.4% vs 1.3%). Degeneracy therefore tracks the
operation, not the generator.

**Consequence for dataset design.** `replace`-derived records are
under-determined repair tasks and should either be excluded from repair
evaluation or scored against the diagnostic rather than the reference text.
They remain perfectly valid as *error-construction* records — the error is
real and exactly targeted; only the inverse repair task is ambiguous. The
current library is 5,615 `replace`, 2,570 `insert`, 1,525 `append`, 50
`delete`, so this decision has real reach and belongs in the release manifest.

## Why Mechanical-SFT is worse than no fine-tuning

E3 reported Mechanical at 0.020 / 0.027 with the *lowest* training loss.
The audit explains it in one number.

| arm | reference repair size in training (p25/p50/p75, diff chars) |
|---|---|
| Mechanical | **1 / 1 / 1** |
| DirectEdit | 11 / 23 / 52 |
| FuzzLang | 25 / 54 / 87 |
| *(evaluation cohorts)* | *≈43–46 median* |

Every mechanical training example is a **one-character** repair. The
loss-minimising policy for that distribution is the identity map, and that is
exactly what the model learned:

| arm | share of parsed predictions that are byte-identical to the input |
|---|---|
| Mechanical | **0.676** (unseen file) / **0.627** (unseen project) |
| DirectEdit | 0.023 / 0.018 |
| FuzzLang | 0.020 / 0.016 |
| Gemma Base | 0.016 / 0.008 |

Two thirds of Mechanical's outputs are the input, unchanged. This is why its
training loss is the lowest and its repair rate the worst, and it makes the
control sharper than originally stated: **matching the token budget does not
match the learning signal.** FuzzLang's training distribution (p50 = 54) is the
closest of the three to what evaluation demands (≈43–46); Mechanical's is off
by a factor of forty.

## Reproduce

```bash
# 1. per-instance audit of every archived generation (2s per configuration)
for cohort in eval_unseen_tu heldout_project; do
  for inst in .artifacts/sft-eval/e3-v0002/*--${cohort}.instances.jsonl; do
    name=$(basename "$inst" "--${cohort}.instances.jsonl")
    PYTHONPATH=src python3 src/repair/run_quality_audit.py \
      --records "data/gen/experiments/e3-eval-cohorts-v0001/${cohort}.jsonl" \
      --instances "$inst" --target-format window-rewrite \
      --out ".artifacts/quality-audit/e3-v0002/${name}--${cohort}.json"
  done
done

# 2. aggregate into this report
A=.artifacts/sft-arms/e3-v0002-multiproject-seed42
PYTHONPATH=src python3 src/repair/run_quality_report.py \
  --audit-dir .artifacts/quality-audit/e3-v0002 \
  --cohort data/gen/experiments/e3-eval-cohorts-v0001/eval_unseen_tu.jsonl \
  --cohort data/gen/experiments/e3-eval-cohorts-v0001/heldout_project.jsonl \
  --injector-library data/gen/experiments/e1-library-replay-v0001/library.jsonl \
  --train-arm "mechanical=$A/mechanical.train.jsonl" \
  --train-arm "direct_edit=$A/direct_edit.train.jsonl" \
  --train-arm "fuzzlang=$A/fuzzlang.train.jsonl" \
  --out-dir data/reports/e3-quality-audit-20260812
```

## Files

- `behaviour_audit.csv` — per cohort and arm: verified fixes, degenerate count
  and share, median accepted edit size, identity-prediction share, and each
  degeneracy flag.
- `degeneracy_by_operation.csv` — the `insert` / `replace` split above.
- `training_edit_size.csv` — reference-repair size distribution per training arm.
- `quality-report.json` — everything above with input paths.

## Limits

These are static edit-shape flags, not semantic equivalence. A prediction that
rewrites a statement into a different but compiling statement counts as
non-degenerate here; proving behaviour preservation would need the projects'
test suites, which this pipeline does not build. The audit therefore bounds the
*obvious* failure mode (delete-to-compile) and does not certify correctness.
