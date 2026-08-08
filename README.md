# FuzzLang

FuzzLang constructs compiler-verified C/C++ error data from the compiler's own
diagnostics. A local Gemma model synthesizes a small, diagnostic-specific
**FuzzLang DSL Injector**; the Injector is replayed on correct, non-test
real-project source code, and patched Clang admits a record only when the
intended typed diagnostic is reproduced exactly.

The project has three deliberately separate data tiers:

- **FuzzLang-Breadth** — compiler-derived paired examples for diagnostic
  coverage;
- **FuzzLang-RealSource** — injected errors in correct, non-test source from
  real projects;
- **NatErr** — naturally occurring historical failures with recovered fixes,
  reserved for external evaluation.

Compiler regression tests are prompt evidence for learning a trigger shape;
they are never FuzzLang record sources.

## Current research checkpoint

The paper scope is the pinned `llvmorg-22.1.8` strict C/C++ diagnostic space of
**1,935** types. For the active `+300 new diagnostic types` goal, the most
recent fixed-input audit is
`data/gen/experiments/clang-test-gap-injector-v0002/strict-injector-coverage-audit-batch0053-direct-fixed.json`:
**1,200 / 1,935**, or **+171** types relative to batch 6. Model candidates and
in-flight replays are not coverage.

Older Breadth summaries report a larger historical composite. They must not be
combined with the active-goal audit until a single release manifest and
reproducible union audit reconcile their input records and Injectors. See the
Progress Report for the current publication gate and experiment status.

## Read first

- [`docs/FuzzLang-Proposal.md`](docs/FuzzLang-Proposal.md) — research claims and
  dataset taxonomy.
- [`docs/plan.md`](docs/plan.md) — executable experiment plan and required
  E1--E4 evidence.
- [`docs/FuzzLang-progress.md`](docs/FuzzLang-progress.md) — current audits,
  live work, and submission readiness.
- [`AGENTS.md`](AGENTS.md) — repository constraints and commands.

## Useful commands

```bash
# Run the unit test suite.
python3 -m pytest -q

# Audit a set of paired records against the pinned diagnostic catalog.
PYTHONPATH=src python3 src/coverage/run_coverage.py \
  --records <records.jsonl> --target 3 --gap-out <uncovered.jsonl>
```

Generated campaigns, request manifests, Injectors, replays, and strict audits
live under `data/gen/experiments/`. The source tree uses a `src/` layout, so
ad-hoc scripts should set `PYTHONPATH=src`.
