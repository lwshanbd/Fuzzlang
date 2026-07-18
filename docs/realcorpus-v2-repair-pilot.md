# realcorpus-v2 repair experiment (usage-bounded pilot)

Date: 2026-07-17. Model: `gpt-5.4-mini`. Verifier: Fuzzlang-patched
Clang 22.1.8. Per-instance matched budget: `E=5120`, `T=5`, `K=4`.

The source-isolated formal eval has 440 instances. The zero-shot b0 baseline
completed on all 440 instances for three seeds. To cap API usage, the remaining
four methods were evaluated on the same deterministic 16-instance prefix for
one seed. This second result is a **directional pilot, not a paper-level main
experiment**. Six initially launched full b1/diag cells were interrupted and
are excluded because `run_sweep.py` writes a cell only on completion.

## Full b0 result (440 instances, 3 seeds)

| metric | result |
|---|---:|
| verified fix-rate | **72.5% +/- 1.0** |
| pooled bootstrap 95% CI | [70.1%, 74.9%] |
| exact-target slice | 72.7% (331 instances/seed) |
| near-miss slice | 71.9% (109 instances/seed) |
| cascade = 1 | 77.6% (321 instances/seed) |
| cascade = 2-5 | 61.7% (87 instances/seed) |
| cascade = 6-10 | 55.6% (15 instances/seed) |
| cascade > 10 | 47.1% (17 instances/seed) |

The cascade result is already useful: b0 degrades monotonically from 77.6% on
single-error cases to 47.1% on cascade-heavy cases.

## Matched pilot (16 instances, seed 0)

The subset has 16 distinct diagnostic names from five LLVM source TUs: 10
exact-target and 6 near-miss instances; cascade buckets are 13 single-error,
2 with 2-5 errors, and 1 with more than 10 errors.

| method | verified fixes | rate | mean turns | mean output tokens |
|---|---:|---:|---:|---:|
| b0 zero-shot | 12/16 | 75.0% | 0.88 | 41 |
| b1 stderr loop | 15/16 | 93.8% | 1.00 | 192 |
| diag | 16/16 | **100.0%** | 1.06 | 175 |
| diag -id | 16/16 | **100.0%** | 1.06 | 163 |
| diag -structure | 15/16 | 93.8% | 1.06 | 258 |

On this pilot, diag is +6.2 points over b1, while removing `diag_id` does not
change outcomes. Removing the structured signal matches b1. With only 16
instances, these differences are not statistically conclusive; the 95% CI for
b1 and -structure is [81.2%, 100%], and the subset has no 6-10 cascade case.

Completed b0 runs recorded 52,912 output tokens. The four new pilot runs
recorded 12,608 output tokens; the b0 pilot row was derived locally from its
completed full run. Interrupted requests are not represented in local result
files, so exact billed usage for those partial cells must be read from the API
provider rather than inferred from this manifest.

Machine-readable results are archived at
`data/repair/releases/realcorpus-v2-pilot16/results.tar.zst`; its checksum and
scope are in the adjacent tracked `manifest.json`.
