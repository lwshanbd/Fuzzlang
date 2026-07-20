# FuzzLang: Progress

Status against `FuzzLang-Proposal.md` and the executable plan in `plan.md`.
LLVM is pinned to `llvmorg-22.1.8`; the current test suite has 325 passing and
5 environment-dependent skips. Detailed generation history is in
`data/gen/README.md`.

## Current Research Position

The paper is now centered on compiler-derived, reusable error generation and
the value of the resulting data:

1. distill compiler diagnostic knowledge into diagnostic-specific Injectors;
2. represent and replay the reusable subset through a deliberately narrow
   FuzzLang DSL;
3. apply Injectors to correct, non-test source from real projects;
4. validate every pair with the pinned compiler and measure diagnostic
   coverage;
5. fine-tune a local open Gemma model and measure repair improvement under
   matched training-token budgets;
6. use a smaller NatErr set of naturally occurring failures for external
   validity.

The earlier typed-diagnostic-versus-stderr repair hypothesis is not a core
claim. Existing evidence shows that the compiler-feedback loop helps, but a
typed diagnostic observation does not materially outperform raw stderr for the
tested strong hosted model.

## Frozen Dataset Tiers

### FuzzLang-Breadth

The high-coverage compiler-derived set contains **13,745 structurally
deduplicated verified records**, split train 10,973 / dev 1,402 / eval 1,370
with provenance isolation.

Headline strict C/C++ coverage:

- **1,538/1,935 diagnostics = 79.5%** at multiplicity at least one;
- **1,194/1,935 diagnostics = 61.7%** at multiplicity at least three.

The denominator starts from 3,891 Clang TableGen error diagnostics, excludes
invocation/environment failures that cannot form broken-code/corrected-code
pairs, and excludes non-standard-C/C++ dialect and hardware-target diagnostics
through the audited `data/gen/out_of_scope.txt` list.

### FuzzLang-RealSource

These are generated errors injected into correct real-project source. They are
not naturally occurring developer errors.

The current test-free LLVM releases contain:

| release | records | observed diagnostics | source TUs | strict coverage |
|---|---:|---:|---:|---:|
| realcorpus-v2 | 1,422 | 681 | 419 | 673/1,935 |
| recipe-replay-v1 increment | 631 | 176 | 256 | +18 over the base |
| recipe-replay-v2 increment | 265 | 93 | 172 | +11 over v1 |
| **combined** | **2,318** | **714** | **847** | **702/1,935 (36.3%)** |

The combined set has **208 diagnostics at multiplicity at least three**. All
three stages require `corrected_src`, have zero source overlap by construction,
and report zero compiler/project test or test-support sources.

### NatErr

Stage 1 has commit-history candidate manifests for eight projects. The current
LLVM source-only filter retained 242 candidates. Stage 2 reproduced **86 failing
files from 75 candidates**, a 31.0% candidate reproduction rate.

This output is useful but is not yet a formal NatErr release: it still needs
corrected-source recovery from each fix commit and project/time-isolated
splitting. A streaming formalizer now performs strict test/test-support
exclusion, fix-commit recovery, paired compiler revalidation, canonical
`Record` conversion, rejection logging, and manifest generation. A three-item
read-only LLVM smoke accepted no records: two fixes were unavailable in the
current shallow sparse checkout, and one compile command referenced a stale
build root and missing generated header. The next NatErr step is therefore to
provide a full historical checkout and reconstruct or relocate the Stage-2
compile environment. The paper target remains 100--300 formal natural failures
from two or three projects, not a large training corpus.

The first executable tier audit found two NatErr test/benchmark source paths and
14 NatErr TU identities that overlap current RealSource. Both groups must be
excluded or isolated before NatErr becomes a valid held-out evaluation set.

## What Is Implemented

- **Foundation:** patched Clang 22.1.8 with `DiagID` emission, diagnostic
  catalog, typed verifier, canonical paired `Record`, structural deduplication,
  compile-database support, and release checks.
- **Coverage:** strict denominator, coverage and multiplicity reports, component
  breakdowns, and uncovered/under-covered gap lists.
- **Breadth generation:** mechanical, compiler-evidence-guided, and
  catalog/model-assisted strategies, all verifier checked.
- **RealSource direct editing:** diagnostic-targeted edits on clean LLVM
  translation units with source/test filtering and formal release gates.
- **Reusable recipe prototype:** extraction of minimal diagnostic-specific
  transformations from verified pairs and replay on unseen real LLVM source.
- **FuzzLang DSL v0/v1:** versioned narrow Injector schemas, canonical
  serialization and hashing, stable Injector IDs, replay limits, backward v0
  compatibility, deterministic fresh identifiers, safe token-boundary
  normalization, and execution through the bounded lexical matcher.
- **Cross-project replay:** project-root-relative provenance, non-LLVM compile
  database replay, stable language inference for compiler commands without an
  explicit `-std`, and formal validation on held-out Abseil source.
- **Tier audit:** streaming Breadth/RealSource/NatErr checks for pairing,
  diagnostics, sources, overlap, schema, and test/test-support paths.
- **Repair harness:** zero-shot, stderr-loop, typed-diagnostic loop, SFT method
  hooks, matched attempt/token envelopes, compiler verification, and bootstrap
  metrics.
- **Local Gemma inference:** Gemma-4-31B is staged on Tioga and serves through a
  high-throughput local vLLM path.
- **Gemma SFT path:** canonical Records normalize to model-neutral repair
  examples, the native Gemma chat template works offline, and real tokenizer
  preflight rejects silent truncation by default. A deterministic localized
  relative-edit target round-trips to the complete source. The current TRL API,
  answer-only loss, text-only Gemma LoRA targeting, bounded `max_steps`, and
  optional FSDP configuration are implemented. Gemma 3 4B completed actual
  32/128-record GPU smokes and saved both adapters.
- **NatErr formalization:** streaming fix recovery, source filtering, two-sided
  verification, canonical paired output, explicit rejection reasons, and
  release manifests are implemented.

## Injector Prototype Results

The recipe system is the working precursor to FuzzLang DSL.

- 1,413 recipes are extracted from 1,422 verified realcorpus-v2 pairs.
- v1 marks 468 recipes portable across source files, spanning 245 target
  diagnostics.
- v2 adds identifier bindings and bounded replacement templates, yielding 594
  portable recipes spanning 306 target diagnostics.
- 127 v2 recipes use identifier bindings and span 95 target diagnostics.
- Replay v1+v2 generated **896 structurally retained records** on **428 unseen
  LLVM TUs** without model/API calls.
- Every retained record was recompiled on both sides; none uses a test source.
- All **594/594** current portable recipes convert to FuzzLang DSL v0 and
  round-trip without semantic loss.
- FuzzLang DSL v1 optionally templates payload-local identifiers with
  collision-free fresh names and normalizes byte-exact intra-token edits. This
  increases the portable set from **594/306 diagnostics** to **1,239/598**.
  Of the 645 additional recipes, 617 use fresh identifiers and 28 come from
  token normalization. A more permissive literal-payload experiment reaches
  1,321/652, but remains opt-in and is not promoted to the main method without
  transfer evidence.
- The replay CLI now executes either legacy recipes or FuzzLang DSL Injectors,
  exports canonical Injector JSONL, and stores Injector identity and schema in
  every generated record and manifest.
- A zero-API held-out LLVM pilot exported all 594 Injectors and generated 30
  records. Formal revalidation accepted and structurally retained **30/30**
  records from 11 previously unused non-test TUs, spanning 27 diagnostics with
  zero base-source overlap. Seventeen records (56.7%) exactly matched their
  target, spanning 16 exact-target diagnostics; all 30 carry Injector IDs.
- A follow-up exact-target diversity run scanned 54 of 120 candidate TUs and
  stopped at its cap of **70 records for 70 distinct target diagnostics**.
  Formal revalidation retained **70/70** from 43 additional non-test TUs, with
  zero source overlap or structural duplication against the preceding 2,348
  records. Together these LLVM experiments raise multiplicity-at-three from
  208 to 215 but add no new coverage@1 diagnostic, as expected for Injectors
  distilled from already observed diagnostics.
- In a matched exact-target comparison on the same 120 held-out LLVM candidate
  TUs and identical compiler budgets, the 594-recipe arm needed 91 TUs and 436
  mutant compilations to reach 100 diagnostics; formal revalidation retained
  99 after removing one structural duplicate. The 1,239-recipe v1 arm reached
  100 diagnostics after 64 TUs and 393 mutant compilations, and formal
  revalidation retained **100/100**. Fifty retained records use a fresh-name
  Injector, and **44 diagnostics are outside the original 306-diagnostic
  portable space**. Both arms contain zero test sources and zero source overlap
  with the preceding 2,418 records.
- In the matched cross-project replay on Abseil commit
  `1e6d60b2ca9356542fe62b73ab010424aa2796cf`, all 159 screened non-test C++
  library TUs compiled cleanly before mutation. With the same 120-TU sample,
  seed, compiler budget, and 100-diagnostic cap, the 594-recipe arm used 763
  mutant compilations and formally retained **97/97** exact-target records from
  64 sources. The 1,239-recipe arm reached the cap after 71 TUs and 548 mutant
  compilations and retained **100/100** from 51 sources. It reaches **46
  diagnostics outside the original 306-diagnostic portable space**, with 55
  fresh-name-backed records. Both arms have zero tests, zero structural
  duplicates, zero source overlap, and project-relative Abseil provenance.

These runs validate the DSL execution/release path and pass the complete
Week-2 FuzzLang DSL gate, including transfer to a second C++ project. They do
not replace the matched method experiment. The remaining method work is to
synthesize/repair Injectors with local Gemma and run the matched
Injector-versus-direct-edit experiment.

## Existing Repair Results: Useful but No Longer the Main Claim

On 1,282/1,370 reproducible Breadth eval instances with a strong hosted model,
matched budget `E=5120`, `T=5`, `K=4`, and three seeds:

| method | verified fix rate | interpretation |
|---|---:|---|
| zero-shot | 72.2% | single-shot baseline |
| stderr loop | 92.8% | compiler feedback is highly useful |
| typed diagnostic loop | 92.9% | effectively tied with stderr |
| no diagnostic ID | 93.1% | ID is not responsible for the gain |
| raw-stderr diagnostic-loop ablation | 92.7% | confirms the near tie |

The loop improves repair by roughly 20 points, but typed diagnostics add only
0.1 point over stderr and use more tokens. This result will be treated as an
exploratory negative result or appendix material.

For realcorpus-v2, the three-seed zero-shot run covers all 440 formal eval
instances and reaches 72.5% mean verified repair. A matched five-method pilot on
16 instances is directional only and is not paper-level evidence. No complete
Gemma SFT comparison has been run.

The offline Gemma tokenizer smoke succeeds on short Breadth data: 32/32 and
128/128 prepared examples fit within 4,096 tokens (the 32-example min/median/max
is 241/253/288 tokens). A preliminary RealSource full-TU prefix exposed a real
representation blocker: only 2/32 examples fit, with median 12,624 and maximum
337,379 tokens. This is now addressed by a deterministic localized window plus
relative single-span edit. The edit is exactly round-tripped into the complete
source before compiler evaluation. All **2,318/2,318** current RealSource
records are eligible; localized windows have min/median/p95/max character
lengths 170/594/850/1,163, and every rendered native-Gemma example fits within
4,096 tokens (min/median/p95/p99/max 201/324/406/452/701). The same target
format must be used across matched SFT arms.

The local training environment now includes `peft==0.18.1`,
`datasets==4.8.5`, and `trl==0.27.2`. The Gemma-4-31B path reached correct
language-only LoRA attachment with 122,429,440 trainable parameters, but FSDP1
stalled on Tioga's 4.18 kernel and FSDP2 failed in Accelerate while treating a
PEFT parameter as a DTensor (`Tensor.device_mesh`). The planned time gate was
enforced instead of spending more GPU time on the distributed stack.

The smaller-family fallback is operational. `google/gemma-3-4b-it` at revision
`093f9f388b31de276ce2de164bdc2081324b9767` completed:

| smoke | token min/median/max | optimizer steps | loss | token accuracy | adapter |
|---|---:|---:|---:|---:|---:|
| 32 records | 255 / 330 / 405 | 1 | 5.566 | 0.5291 | 119,280,712 bytes |
| 128 records | 202 / 337.5 / 702 | 2 | 5.600 -> 2.889 | 0.5105 -> 0.6703 | 119,280,712 bytes |

Both runs use native chat formatting, the same localized relative-edit target,
answer-only loss, BF16, LoRA rank 16, seed 42, and zero implicit truncation.
Adapters and ignored run manifests are archived under `.artifacts/`; manifests
contain the model revision, source-data SHA-256, adapter SHA-256, configuration,
and metrics. These bounded smokes validate the training path but are not a full
epoch or paper-level fine-tuning result. Adapter reload/local serving and a
fixed compiler-verified repair smoke remain the next SFT gate items.

## Main Missing Evidence

The revised paper requires four results that do not yet exist:

1. **Injector method result:** a matched comparison of FuzzLang DSL Injector
   reuse, transfer, exact-target yield, and cost against direct per-record
   Gemma editing.
2. **Multi-project RealSource result:** scale the successful Abseil transfer
   pilot into a release and add a held-out C project, with coverage and
   provenance isolation.
3. **Gemma SFT result:** Gemma Base versus matched-token Mechanical-SFT,
   DirectEdit-SFT, and FuzzLang-SFT, evaluated on unseen TUs/projects.
4. **NatErr result:** a formal paired natural-error release and external-validity
   evaluation.

Until these results exist, the project has a strong construction substrate and
coverage result but not a complete paper-level causal demonstration of dataset
value.

## Immediate Parallel Work

### A. Freeze Data and Evaluation

- enforce Breadth/RealSource/NatErr release boundaries;
- freeze project-, TU-, and Injector-isolated splits;
- attach generation method and Injector identity to every new record;
- keep the strict 1,935 denominator and release gates reproducible.

### B. Gemma SFT Smoke

- preserve the completed canonical-data, native-template, offline tokenizer,
  32/128 preparation path, and strict token preflight;
- preserve the completed round-trippable relative-edit representation and use
  it identically across matched SFT arms;
- preserve the pinned local training dependencies and the completed Gemma 3 4B
  32/128-record GPU smoke path;
- keep the documented 31B FSDP incompatibility out of the critical path;
- load the adapter into local inference and run compiler-verified repair;
- then run an approximately 1,000-record pilot before the matched SFT arms.

### C. FuzzLang DSL v1 Transfer

- integrate the completed schema with generation manifests and Record
  provenance (completed for the replay path);
- preserve v0 compatibility and the verified v1 expansion to 1,239 portable
  recipes / 598 diagnostics;
- preserve the matched formally revalidated LLVM and Abseil evidence;
- connect local Gemma to Injector synthesis/repair;
- freeze v1 and use a recipe+direct-edit hybrid if cross-project transfer
  fails.

## Targets and Schedule Guardrails

- RealSource core goal: 10,000--30,000 records across at least three projects.
- RealSource strict coverage goal: approximately 1,000/1,935 diagnostics.
- RealSource multiplicity-at-three goal: 350--400 diagnostics; 600 is stretch.
- NatErr goal: 100--300 formal pairs from two or three projects.
- No paid-API dependency in the final generation, SFT, or evaluation pipeline.
- No general AST transformation language before the main SFT result.
- No additional full typed-diagnostic-versus-stderr sweeps.
- No test/test-support source in RealSource or NatErr.

The detailed six-week schedule, gates, experimental arms, metrics, fallback
rules, and artifact requirements are maintained in `docs/plan.md`.
