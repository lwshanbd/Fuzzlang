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

The paper headline is a stricter scope, not the full-catalog ratio:
`paper_scope_summary.csv` derives the frozen **1,935** standard C/C++
source-diagnostic denominator from the same catalog and records the current
**1,029 / 1,935 (53.2%)** Injector coverage. It excludes invocation or
environment diagnostics and the audited non-standard-dialect/hardware-target
name list. The 1,178/3,891 figure remains an operational breadth audit.

- `summary.csv` contains the headline counts.
- `paper_scope_summary.csv` contains the frozen paper-scope denominator and
  numerator, alongside the full-catalog accounting reconciliation.
- `injector_diagnostic_inventory.csv` maps every portable Injector ID to its
  declared target and states whether that target has a strict paired replay.
- `diagnostic_injector_summary.csv` aggregates the Injector inventory by
  target.
- `uncovered_tablegen_errors.csv` lists each remaining catalog error type,
  including Clang-test reachability and non-test emission-context metadata.

The CSVs contain metadata only: they do not copy program source, test source,
Injector payloads, or training records.
