# Strict Injector Coverage Snapshot — 2026-08-04, Test-Gap Batch 1

This is a full strict-coverage snapshot after the first mode-routed
Clang-test-guided gap campaign.  Its audit is
`data/gen/experiments/clang-test-gap-injector-v0002/strict-injector-coverage-audit-batch0001.json`.
It uses the pinned `llvmorg-22.1.8` TableGen catalog.

Clang regression tests provide prompt and reachability evidence only.  Every
accepted record in this audit has a clean non-test source parent, a paired
`corrected_src`, a portable FuzzLang Injector, and an exact primary typed
diagnostic after replay.

- `summary.csv` contains headline counts.
- `injector_diagnostic_inventory.csv` maps every portable Injector ID to its
  target diagnostic.
- `diagnostic_injector_summary.csv` aggregates Injector count, languages, and
  operations per target diagnostic.
- `uncovered_tablegen_errors.csv` lists every TableGen error diagnostic not
  strictly covered, including test reachability and non-test emission-context
  evidence for prioritization.

The preceding baseline snapshot remains available at
`data/reports/strict-injector-coverage-20260804/`.
