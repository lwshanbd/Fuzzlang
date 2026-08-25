# FuzzLang-RealSource v1

> **Known defect (2026-08-25): 25% of these records label themselves.**
> Injected placeholders were named `fuzzlang_tmp`, so **3,274 of 13,007 records
> carry the literal string `fuzzlang` on the broken side and never on the fixed
> side** (train 35%, eval_unseen_tu 33%, heldout_project 13%). A model can
> locate the error by searching for it rather than reading the code, and a
> fine-tuned one did -- inflating measured repair rates by about 4 points. See
> [e9-ablation-20260825](../../../reports/e9-ablation-20260825/README.md).
>
> The generator no longer emits identifying names and the freeze now refuses
> such records (`provenance_marker`), so **v1 would not pass its own gate
> today**. Until v2 is rebuilt, report results on the unmarked subset and treat
> v1 as superseded for training and evaluation alike.

Compiler-verified compilation errors introduced into correct source from 13 real
C/C++ projects. Built by replaying the FuzzLang Injector library — **no GPU
time and no model calls**. Every record is a pair: source that compiles, and the
same source with one injected error that a pinned Clang confirms.

Frozen 2026-08-14. Verified against Clang at `llvmorg-22.1.8`.

## What is in it

| split | records | diagnostics | ≥3 examples | source files | injectors |
|---|---:|---:|---:|---:|---:|
| `train` | 5,742 | 427 | 306 | 1,949 | 461 |
| `eval_unseen_tu` | 1,711 | 138 | 101 | 376 | 140 |
| `heldout_project` | 5,554 | 224 | 202 | 1,389 | 283 |
| **total** | **13,007** | **514** | — | 3,714 | 610 |

`train` and `eval_unseen_tu` come from the same nine projects but never the same
file. `heldout_project` is four projects — Abseil, FFmpeg, leveldb, json-c —
that contribute nothing to training at all.

Splits were fixed **before** any record was generated, using a hash of the
source file. Growing the pool never moves a file from one split to another, so
a source used in training can never later appear in evaluation. Each record
carries its own assignment in `provenance.detail.source_split`.

## Two imbalances to be aware of

**Projects are not evenly represented.** LLVM is 65% of `train` (3,743 of
5,742) and FFmpeg is 87% of `heldout_project` (4,821 of 5,554). This follows
from how much clean, compilable source each project offers, not from any
sampling choice. Anything reported per project should say so; and note that in
this data a project's records also cluster on particular diagnostics, so a
per-project number is close to a per-diagnostic number wearing a different name
(see `data/reports/e3-project-confound-20260813/`).

**The language mix flips between splits.** `train` is 75% C++; `heldout_project`
is 88% C, because FFmpeg dominates it. That makes train→heldout a language shift
as well as a project shift. Useful for a transfer claim, but it has to be stated
rather than presented as a pure project shift.

## What every record satisfies

Checked over all 13,007 at freeze time; a single failure aborts the freeze.

| gate | meaning |
|---|---|
| `corrected_src_present` | the correct version is always included |
| `corrected_differs` | it is not identical to the broken version |
| `no_test_source` | no test or test-support file is ever a record |
| `no_vendored_source` | no fetched dependency (`_deps/`, `third_party/`, …) |
| `target_not_relabelled` | the error is the one the injector aimed for, not whatever happened to fire |
| `primary_matches_target` | the compiler's first error matches that target exactly |
| `injector_recorded` | the injector that produced it is named |
| `unique_record_id` | no duplicates |
| `provenance_marker` | **added 2026-08-25**; no token identifying the generator on the broken side only. **v1 predates this gate and 3,274 records fail it.** |

2,090 records were dropped for `no_vendored_source`. They were real records, but
their source belonged to a dependency the project had fetched, so attributing
them to that project would have been wrong — and in one case put Abseil source
into training while Abseil was a held-out evaluation project.

## What is deliberately *not* here

- **Errors we did not create.** Natural errors from commit history are a
  separate and much smaller problem; see `data/reports/e4-naterr-20260812/`.
- **Records whose target was relabelled.** When a mutation produces *some*
  error rather than the requested one, that is evidence an error fired, not
  evidence the gap was reached. 685 such records exist elsewhere and are
  excluded here.
- **Anything from Clang's own test suite.** Compiler tests are used only as
  evidence for understanding a diagnostic, never as records.

## Verify it

```bash
sha256sum -c SHA256SUMS      # full digests, also in release-manifest.json
```

A compressed bundle sits beside this directory:
`../fuzzlang-realsource-v1.bundle.tar.zst`, 51 MB, sha256
`ab026d85ba43beca85a893c95c70fff9caf5a2f427b8b29538dc57bbf612a096`. Extracting
it and re-running `sha256sum -c SHA256SUMS` reproduces all 13,007 records.

Rebuild from the generation output:

```bash
E1=data/gen/experiments/e1-library-replay-v0001
R=(); for arm in lexical-train lexical-eval_unseen_tu lexical-heldout_project \
                 append-train append-eval_unseen_tu append-heldout_project; do
  R+=(--records "$E1/$arm/records.jsonl")
done
PYTHONPATH=src python3 src/gen/fuzzlang_dsl/run_freeze_release.py "${R[@]}" \
  --release fuzzlang-realsource-v1 --created 2026-08-14 \
  --injector-library "$E1/library.jsonl" \
  --out-dir data/gen/releases/fuzzlang-realsource-v1
```

## Where the numbers in the papers come from

- Coverage: `data/reports/strict-coverage-20260812-release-union/`
- Construction cost and reach: `data/reports/e1-construction-20260812-devendored/`
- Fine-tuning result: `data/reports/e3-sft-value-20260811/` and
  `data/reports/e5-scaling-20260814/`
