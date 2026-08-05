# Strict Injector Coverage Snapshot — 2026-08-05, Test-Gap Batch 6

This completed strict-coverage snapshot extends batch 5 with the accepted
C++98 local-Gemma rerun. It adds one exact target diagnostic,
`err_empty_scalar_initializer`, under the pinned `llvmorg-22.1.8` catalog.

Only compiler-verified outputs enter this snapshot. A core record must retain
a clean, non-test parent and `corrected_src`; a portable FuzzLang Injector must
be recorded in provenance; and the replayed primary typed diagnostic must
exactly equal the requested target. Clang regression tests remain trigger
evidence only; no test or test-support source is a FuzzLang record.

The release audit is
`data/gen/experiments/clang-test-gap-injector-v0002/strict-injector-coverage-audit-batch0006.json`.
It audits 9,342 unique portable Injectors and 6,920 strict paired records,
covering 1,178 of 3,891 catalog error diagnostics.

- `summary.csv` contains the headline counts.
- `injector_diagnostic_inventory.csv` maps every portable Injector ID to its
  declared target and states whether that target has a strict paired replay.
- `diagnostic_injector_summary.csv` aggregates the Injector inventory by
  target.
- `uncovered_tablegen_errors.csv` lists each remaining catalog error type,
  including Clang-test reachability and non-test emission-context metadata.

The CSVs contain metadata only: they do not copy program source, test source,
Injector payloads, or training records.
