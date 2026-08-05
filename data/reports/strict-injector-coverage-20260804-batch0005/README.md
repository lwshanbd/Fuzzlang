# Strict Injector Coverage Snapshot — 2026-08-05, Test-Gap Batch 5

This completed strict-coverage snapshot extends batch 4 with three completed
local-Gemma campaigns: a C23 standard route, an OpenMP route, and a C++23
retry route.  Their 15 accepted paired records add 15 exact target diagnostic
types under the pinned `llvmorg-22.1.8` catalog.

Only compiler-verified outputs enter this snapshot.  A core record must carry
a clean, non-test parent and `corrected_src`; a portable FuzzLang Injector must
be recorded in provenance; and the replayed primary typed diagnostic must
exactly equal the target.  Clang regression tests remain trigger evidence only;
no test or test-support source is a FuzzLang record.

The release audit is
`data/gen/experiments/clang-test-gap-injector-v0002/strict-injector-coverage-audit-batch0005.json`.
It audited 9,345 unique portable Injectors and 6,923 strict paired records,
covering 1,181 of 3,891 catalog error diagnostics.

- `summary.csv` contains the headline counts.
- `injector_diagnostic_inventory.csv` maps each portable Injector ID to its
  declared target and states whether that target now has a strict paired replay.
- `diagnostic_injector_summary.csv` aggregates the Injector inventory by target.
- `uncovered_tablegen_errors.csv` lists every remaining catalog error type,
  including Clang-test reachability and non-test emission-context metadata.
- `staged_direct_injector_targets_20260805.csv` is pending work only: 198
  current strict gaps, represented by 236 direct requests and 696 clean-source
  witnesses. Its rows are Gemma requests, not Injector artifacts or data
  records; each remains outside the strict count until exact compiler replay
  accepts it.

All CSVs contain metadata only: they do not copy program source, test source,
Injector payloads, or training records.
