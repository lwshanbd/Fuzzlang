# Release-union strict coverage — 2026-08-12

**This is the number the paper should quote for diagnostic coverage:
`1,208 / 1,935` paper-scope error diagnostics (62.4%), strict rule.**

It is the canonical batch-6 campaign audit *plus* the multi-project library
replay (E1), folded in under explicit labels through one command, with every
input checksummed in `input_manifest.csv` (1,977 files).

```
E1=data/gen/experiments/e1-library-replay-v0001
EXTRA=()
for arm in lexical-train lexical-eval_unseen_tu lexical-heldout_project \
           append-train append-eval_unseen_tu append-heldout_project; do
  EXTRA+=(--extra-input "e1-${arm}:${E1}/library.jsonl:${E1}/${arm}/records.jsonl")
done
PYTHONPATH=src python3 src/gen/fuzzlang_dsl/run_canonical_strict_audit.py \
  "${EXTRA[@]}" \
  --audit-out data/gen/experiments/clang-test-gap-injector-v0002/release-union-strict-audit-20260812.json \
  --report-dir data/reports/strict-coverage-20260812-release-union
```

The admission gate is unchanged from
[the 08-07 canonical audit](../strict-injector-coverage-20260807-canonical/README.md):
clean non-test parent TU, `corrected_src` present and different, the compiler's
primary typed diagnostic exactly equal to the record's target, a portable
Injector that matches provenance, and an error diagnostic in the pinned
`llvmorg-22.1.8` catalog. All 15,097 E1 records enter with **zero rejections**.

## What folding E1 in changes

| | canonical 08-07 | release union 08-12 | delta |
|---|---:|---:|---:|
| **paper-scope types, strict** | 1,195 | **1,208** | **+13** |
| paper-scope types, inclusive | 1,242 | 1,242 | 0 |
| new vs batch 6, strict | +214 | **+227** | +13 |
| strict verified records | 6,850 | **21,947** | +15,097 |
| **types reachable only by relabelling** | 47 | **34** | **−13** |

**The interesting line is the last one.** E1 added *no* types under the
inclusive rule — every one of the 13 was already counted there. What it added
is **exactness**: those 13 types were previously reached only by records whose
`target_diag` had been relabelled to whatever error the mutation happened to
emit (`opportunistic_observed_diagnostic`), which is evidence that *an* error
fired, not that the requested gap was hit. Replaying the library over real
project source reached them **on target**, so they move out of the soft column.

The 13 types promoted from relabel-only to exactly-targeted:

| diagnostic | E1 records |
|---|---:|
| `err_addr_ovl_no_viable` | 80 |
| `err_atomic_op_needs_atomic_int_or_ptr` | 50 |
| `err_allocation_of_abstract_type` | 32 |
| `err_constexpr_body_no_return` | 14 |
| `err_illegal_initializer` | 14 |
| `err_auto_different_deductions` | 10 |
| `err_bad_parameter_name` | 10 |
| `err_use_with_wrong_tag` | 5 |
| `err_param_redefinition` | 2 |
| `err_argument_invalid_range` | 1 |
| `err_atomic_op_needs_trivial_copy` | 1 |
| `err_inline_non_function` | 1 |
| `err_typecheck_statement_requires_integer` | 1 |

This is a claim worth stating directly: **applying the Injector library to
source it has never seen both extends coverage and hardens coverage it already
had.** 685 records still rest on relabelled targets and 34 paper-scope types
still depend on them alone — down from 47.

## Which number to quote where

Four coverage figures circulate in the docs and they measure four different
populations. They must never be added or substituted.

| number | population | artifact |
|---|---|---|
| **1,208 / 1,935 (62.4%)** | **everything released, strict gate — the headline** | this report |
| 1,242 / 1,935 | same inputs, relabelled targets allowed | this report, `inclusive` column |
| 1,538 / 1,935 | historical FuzzLang-Breadth composite (self-contained fragments, different input union and gate) | `docs/FuzzLang-progress.md` §Breadth |
| 459 / 1,935 | one capped replay pass over real project source only, de-vendored | `../e1-construction-20260812-devendored/` |

The 1,538 Breadth figure is **not** comparable to this one and is not the
paper's coverage claim; it predates the strict admission gate and draws on a
different input union. Quote 1,208 with the strict gate, and cite 459 only as
"what one capped real-source pass realizes", never as the tool's reach.

## Files

- `summary.csv` — both rules, all counters.
- `diagnostic_record_map.csv` — every covered diagnostic mapped to its records,
  Injector IDs, campaigns, projects, and languages.
- `uncovered_paper_scope_gaps.csv` — the 727 paper-scope types still uncovered.
- `input_manifest.csv` — SHA-256, size, and row count of all 1,977 inputs.
