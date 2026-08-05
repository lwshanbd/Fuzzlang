# Strict Injector Coverage Snapshot — 2026-08-04, Test-Gap Batch 2

This is the current completed strict-coverage snapshot. It extends the
batch-1 snapshot with the completed C++11 plain-language campaign. Its audit
is `data/gen/experiments/clang-test-gap-injector-v0002/strict-injector-coverage-audit-batch0002.json`, and it uses the pinned
`llvmorg-22.1.8` TableGen catalog.

The snapshot includes only completed, compiler-verified campaign outputs. The
two concurrently running C++23 campaigns are intentionally excluded until
their manifests and release gates complete, so every number here is stable and
reproducible.

Clang regression tests provide prompt and reachability evidence only. No test
or test-support source is included as a FuzzLang record. Every accepted core
record has a clean non-test source parent, paired `corrected_src`, a portable
FuzzLang Injector, and an exact primary typed diagnostic after replay.

- `summary.csv` gives the headline counts.
- `injector_diagnostic_inventory.csv` is the exact one-row-per-Injector map
  from portable Injector ID to its target diagnostic.
- `diagnostic_injector_summary.csv` is the per-diagnostic aggregate, including
  Injector count, languages, and operations.
- `uncovered_tablegen_errors.csv` is the complete current TableGen gap list;
  it includes component, diagnostic template, test reachability, and non-test
  emission-context availability for prioritization.

These CSVs contain metadata only: they contain neither program source nor
Injector payloads. An Injector target is not counted as covered solely because
an Injector exists; strict coverage requires a paired record whose typed
compiler diagnostic exactly equals the target.
