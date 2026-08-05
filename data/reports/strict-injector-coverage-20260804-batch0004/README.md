# Strict Injector Coverage Snapshot — 2026-08-04, Test-Gap Batch 4

This is the current completed strict-coverage snapshot for the pinned
`llvmorg-22.1.8` TableGen catalog.  It extends batch 3 with completed local
Gemma runs for the second MS-extension batch and the first OpenACC batch.
Their 18 accepted paired records add 18 exact target diagnostic types.

Only compiler-verified outputs enter this snapshot.  In particular, a core
record must have a clean non-test parent source and `corrected_src`; a portable
FuzzLang Injector must be recorded in its provenance; and the replayed primary
typed compiler diagnostic must exactly equal the Injector target.  Clang
regression tests provide prompt and reachability evidence only.  No test or
test-support source is a FuzzLang record.

The audit input and release decision are recorded in
`data/gen/experiments/clang-test-gap-injector-v0002/strict-injector-coverage-audit-batch0004.json`.
The snapshot contains 9,330 unique portable Injectors, 6,908 verified paired
records, and 1,166 covered TableGen error diagnostics out of 3,891.

- `summary.csv` contains headline counts.
- `injector_diagnostic_inventory.csv` is the one-row-per-Injector mapping:
  Injector ID → declared Clang diagnostic target.  The
  `strict_diagnostic_covered` column distinguishes declared targets from ones
  backed by at least one accepted paired replay.
- `diagnostic_injector_summary.csv` aggregates Injector count, language, and
  operation by target diagnostic.
- `uncovered_tablegen_errors.csv` lists every catalog error diagnostic not yet
  covered, with component, TableGen message, Clang-test reachability, and the
  availability of a non-test emission context.
- `staged_direct_injector_targets_20260805.csv` is a separate pending-work
  ledger.  It aggregates direct local-Gemma requests by diagnostic target:
  208 current strict gaps are represented by 246 requests and 726 clean-source
  witnesses.  Every row is explicitly marked as not strictly covered.  A row
  describes a request for an Injector, not an Injector artifact or a dataset
  record; it can enter a future inventory only after exact-target compiler
  replay accepts it.

These CSVs contain metadata only: they do not copy program source, Clang test
source, Injector payloads, or training records.  Outputs from active or not
yet audited campaigns are deliberately absent and must pass the same gate
before a later snapshot incorporates them.
