# Strict Injector Coverage Snapshot — 2026-08-04

This snapshot is derived from the fresh full-catalog strict audit
`strict-injector-coverage-audit-live-20260804-summary.json`, using the pinned
`llvmorg-22.1.8` TableGen catalog.

- `summary.csv` records the headline counts.
- `injector_diagnostic_inventory.csv` has one row per unique portable
  FuzzLang Injector used by the audit. `strict_diagnostic_covered=true` means
  that the Injector's target diagnostic has at least one accepted strict paired
  record; it does not claim that every Injector row itself was independently
  replayed.
- `diagnostic_injector_summary.csv` has one row per target diagnostic named by
  a portable Injector. It aggregates Injector count, languages, and operations
  and distinguishes an Injector target from a diagnostic with accepted strict
  paired data.
- `uncovered_tablegen_errors.csv` has one row per TableGen `Error` diagnostic
  not covered by the strict audit. `test_reachable` is prompt-only Clang test
  evidence and `emission_context_available` denotes non-test Clang emission
  source context. Neither column allows a Clang test source to enter the
  dataset.

Regenerate the snapshot with:

```bash
PYTHONPATH=src python3 src/coverage/export_injector_inventory.py \
  --audit data/gen/experiments/compiler-evidence-injector-v0/scale-witness-v1/strict-injector-coverage-audit-live-20260804-summary.json \
  --test-reachable data/gen/experiments/clang-test-reachability-audit-20260726/overlap.txt \
  --test-reachable data/gen/experiments/clang-test-reachability-audit-20260726/clang-test-only.txt \
  --emission-index data/gen/experiments/compiler-evidence-injector-v0/scale-witness-v1/clang-emission-index.json \
  --injector-out data/reports/strict-injector-coverage-20260804/injector_diagnostic_inventory.csv \
  --diagnostic-out data/reports/strict-injector-coverage-20260804/diagnostic_injector_summary.csv \
  --uncovered-out data/reports/strict-injector-coverage-20260804/uncovered_tablegen_errors.csv \
  --summary-out data/reports/strict-injector-coverage-20260804/summary.csv
```
