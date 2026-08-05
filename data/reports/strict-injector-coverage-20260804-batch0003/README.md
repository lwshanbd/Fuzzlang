# Strict Injector Coverage Snapshot — 2026-08-04, Test-Gap Batch 3

This is the current completed strict-coverage snapshot. It extends batch 2
with two completed ordinary C++23 campaigns and two independently
compiler-verified cross-target replay records. Its audit is
`data/gen/experiments/clang-test-gap-injector-v0002/strict-injector-coverage-audit-batch0003.json`, using the pinned `llvmorg-22.1.8` TableGen catalog.

Only completed, compiler-verified outputs enter this snapshot. The next two
disjoint C++23 batches are prepared but intentionally excluded until their
manifests and release gates complete.

Clang regression tests provide prompt and reachability evidence only. No test
or test-support source is a FuzzLang record. Every accepted core record has a
clean non-test source parent, paired `corrected_src`, a portable FuzzLang
Injector, and an exact primary typed diagnostic after replay.

- `summary.csv` gives the headline counts.
- `injector_diagnostic_inventory.csv` gives the exact one-row-per-Injector
  mapping from portable Injector ID to target diagnostic.
- `diagnostic_injector_summary.csv` aggregates Injector count, languages, and
  operations by target diagnostic.
- `uncovered_tablegen_errors.csv` is the complete current TableGen gap list,
  including component, message template, test reachability, and non-test
  emission-context availability.

The CSVs contain metadata only, not program source or Injector payloads. An
Injector target enters strict coverage only when a paired record's typed
compiler diagnostic exactly equals the Injector target.
