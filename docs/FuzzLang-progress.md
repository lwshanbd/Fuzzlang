# FuzzLang: progress

Status against `FuzzLang-Proposal.md`. LLVM pinned to `llvmorg-22.1.8`; test
suite 175 passing. Gen data detail is in `data/gen/README.md`.

## Headline

**Diagnostic coverage (proposal's #1 metric): 1538 / 1935 in-scope C/C++ error
diagnostics = 79.5%** (61.7% with ≥3 examples). The denominator is the 3891 error
diagnostics in Clang's TableGen, minus invocation/environment errors (not
code pairs) and non-C/C++ dialect/target errors (Objective-C, OpenMP, GPU, MS,
etc.) that are out of scope by design.

## What's built and run

- **Foundation** — patched clang 22.1.8 emitting `DiagID` (the rebased patch),
  diagnostic catalog (3891 errors), typed verifier, record schema, dedup. Done.
- **Coverage** — the metric + gap list; `--code-only` and `--exclude-names`
  filters define the in-scope denominator. Done.
- **Gen** — all three strategies, verifier-checked, run at scale:
  mechanical mutation; guided generation from Clang's tests (multi-config +
  RUN-line flag mining); and model-assisted/catalog generation (gpt-5.4-mini,
  gpt-5.5 for the hard tail). These supply the verified records behind the
  coverage above.
- **Dataset** — 13,745 deduped verified records, split train 10,973 /
  dev 1,402 / eval 1,370, provenance-isolated (no source leaks across splits).
- **Scope filter** — every diagnostic classified strict-C/C++ vs out-of-scope
  (keywords + LLM, audited by sub-agents); list at `data/gen/out_of_scope.txt`.

## Not yet run

- **Repair** (metric #2, verified fix-rate): loop + baselines + `diag` method
  reused as-is; ready to run on the new splits.
- **Real** (metric #3, real-world eval): miners present; not reproduced this cycle.

## Next

1. Run repair baselines + `diag` on dev/eval → first verified fix-rate.
2. Reproduce a Real eval slice.
3. Raise multiplicity toward ≥3 on the covered tail.
