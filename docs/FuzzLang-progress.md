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
- **Repair** (metric #2) — baselines + `diag` + causal ablations run on the eval
  split; first verified-fix-rate numbers below.

## Repair: verified fix-rate (metric #2)

First numbers, on the **1,282 / 1,370 eval instances that reproduce** under the
patched clang (93.6%; all exact-diagnostic match — the rest needed `-cc1`-only
flags we don't carry). Same base model (`gpt-5.4-mini`) for every method,
**matched budget** E=5120 (T=5, K=4), 3 seeds, verifier = patched clang 22.1.8.
Fix-rate is mean ± std across seeds; CI is a 95% bootstrap over the pooled instances.

| method | fix-rate (micro) | 95% CI | macro | turns | out-tok |
|---|---|---|---|---|---|
| b0  zero-shot, single-shot        | 72.2 ± 0.3 | [70.7, 73.6] | 70.7 | 0.95 | 33 |
| b1  stderr-text loop              | 92.8 ± 0.5 | [92.0, 93.6] | 94.2 | 1.21 | 258 |
| **diag**  typed diagnostic signal | 92.9 ± 0.2 | [92.1, 93.7] | 93.4 | 1.37 | 315 |
| −id   (structure, no diag_id)     | 93.1 ± 0.4 | [92.3, 93.9] | 93.6 | 1.38 | 315 |
| −struct (raw stderr, diag loop)   | 92.7 ± 0.2 | [91.9, 93.5] | 92.9 | 1.22 | 262 |

**Read honestly:** the *loop* is what moves the needle (b0 72% → any loop 93%);
the typed diagnostic signal buys nothing over raw stderr on this eval —
**diag − b1 = +0.1 pts** (within seed noise: per-seed −0.4/+0.7/−0.1), and the
−id / −struct ablations agree (all ~93%). diag even spends more tokens (315 vs
258) and turns (1.37 vs 1.21) for the same rate. Per-family the effect flips
sign and cancels (structure helps `err_module` +30, `err_static_assert` +8;
hurts `err_module_not` −9, `err_ovl_no_viable` −7). Caveat: `gpt-5.4-mini` is a
strong model and these are short, single-diagnostic programs where stderr
already carries the fix — the structured signal is most likely to pay off for a
*smaller / SFT'd* policy (b2/b3, untested) and on the harder Real split, not a
frontier zero-shot model.

## Not yet run

- **Real** (metric #3, real-world eval): miners present; not reproduced this cycle.
- **b2/b3** (SFT policy): no LoRA adapter trained yet — the setting where the
  diagnostic signal is most likely to matter.

## Next

1. Reproduce a Real eval slice → run the same ladder on real failures.
2. Train a small-model LoRA (b2/b3) and re-test diag − b1 where the base policy
   is weaker.
3. Raise multiplicity toward ≥3 on the covered tail.
