# FuzzLang: Progress

Status against `FuzzLang-Proposal.md` and the executable plan in `plan.md`.
LLVM is pinned to `llvmorg-22.1.8`; the current test suite has 503 passing and
5 environment-dependent skips. Detailed generation history is in
`data/gen/README.md`.

## Live Strict Injector Campaign (2026-07-25)

The active coverage objective is **at least 1,000 distinct Clang TableGen
error diagnostics**, measured only by the current strict FuzzLang Injector
audit.  The latest independent live audit reports **638 / 3,891** catalog
error types, backed by 5,505 paired records and 7,575 unique portable
Injectors.  It rejects records that lack the concrete Injector required by
their replay provenance and excludes test/test-support sources.

This is the authoritative live metric for the expansion campaign.  It must
not be compared directly with the historical 1,935-diagnostic denominator
below: that older denominator is a scoped paper-analysis subset.  The live
campaign uses the full pinned TableGen error catalog, source-clean-gates every
parent TU, requires an exact typed compiler diagnostic after Injector replay,
and records the resulting paired source.

The queue contains (1) compiler-observed uncovered gaps, (2) the complete
ordinary-C++ LLVM gap pool, and (3) an archived cross-project Abseil gap pool
that is submitted incrementally as scheduler slots become available.  The
only completion criterion is a fresh full-catalog strict-audit artifact at or
above 1,000 types.

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
- **Compiler-evidence Injector synthesis:** an offline Gemma-4-31B loop reads
  TableGen/emission evidence plus verbatim correct production snippets, emits
  one constrained FuzzLang Injector, semantically gates it on the supplied
  snippets, and replays it only through the paired compiler verifier.
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
- **Gemma SFT and evaluation path:** canonical Records normalize to
  model-neutral repair examples, the native Gemma chat template works offline,
  and real tokenizer preflight rejects silent truncation by default. Both a
  localized offset edit and a bounded JSON `corrected_window` reconstruct the
  complete translation unit; the latter is now primary after the offset target
  failed held-out generalization. The current TRL API, answer-only loss,
  text-only Gemma LoRA targeting, bounded `max_steps`, optional FSDP, explicit
  activation-checkpoint control, immutable run manifests, adapter reload, base-
  only control, structured-output parsing, and pinned-Clang evaluation are
  implemented. The verifier can select separate patched C/C++ drivers, and an
  offline audit can recompile archived generations and measure gold-relative
  edit size, changed lines, and deletion flags. Gemma 3 4B completed 32/128-
  record GPU smokes and a formal 876-record three-epoch pilot.
- **RealSource Mechanical:** a bounded deterministic runner samples existing
  text mutations on corrected, non-test LLVM translation units, clean-gates
  every parent, uses separate C/C++ drivers, and records compiler budgets and
  rejection reasons. The scale run scanned 250 sources, issued 250 baseline
  plus 560 mutant compiles, accepted 494 pairs before global caps, and retained
  297 records across 59 diagnostics. Of the 250 sources, 248 produced an
  accepted mutant. The retained output has zero test paths, zero missing
  corrected sources, zero API use, and records SHA-256
  `ae12cdd2cadeaff96d857550312faf7691840a46dc8b523cb357c60a44e3a2ab`.
  It covers 59/3,489 code-only diagnostics, reaches multiplicity three for 27,
  and adds seven diagnostic names not present in the existing RealSource plus
  recipe-replay pools.
- **Matched-arm construction:** a deterministic builder validates Mechanical,
  DirectEdit, and FuzzLang generation provenance; maps legacy replay recipes to
  canonical Injector IDs without changing replay semantics; rejects eval
  overlap at the TU, record, full-source, paired-source, and localized-input
  levels; counts native Gemma rendered and completion tokens; and archives
  checksummed arm manifests. The strict frozen build contains 297 records and
  exactly 144,710 rendered tokens in each arm. Completion-token totals are
  58,907/57,372/57,564 for Mechanical/DirectEdit/FuzzLang. The arms contain
  59/183/150 diagnostics and 240/164/222 source TUs; FuzzLang uses 131 distinct
  Injector IDs. Eval leakage is zero, as are cross-arm exact localized-input,
  corrected/erroneous-pair, and record-ID overlaps. The 124 source TUs shared
  across arms are intentionally retained and explicitly reported as a control
  for real-source domain, not described as full cross-arm source isolation.
  The E3 data gate has passed. All three arms completed three epochs and 57
  optimizer steps using the same memory-safe batch-size-one/gradient-
  accumulation-two configuration. Their train losses are 0.03362/0.05672/
  0.03799; these are archived run diagnostics, not repair evidence. An earlier
  FuzzLang job hit a node ECC fault and an earlier DirectEdit job hit a longest-
  batch OOM, so every arm was restarted uniformly. Compiler evaluation is in
  now complete on the fixed 32-example LLVM slice. Base/Mechanical/DirectEdit/
  FuzzLang verified Fix@1 is 5/5/15/16; exact match is 0/1/6/11. All 32 outputs
  per arm parse, all 32 corrected sources pass the driver-correct gate, and no
  ground-truth rows are stale. FuzzLang and DirectEdit share 13 compiler fixes,
  with three FuzzLang-only and two DirectEdit-only; all six DirectEdit exact
  matches are shared and FuzzLang has five additional exact matches. Mechanical
  has zero degenerate compiler fixes; DirectEdit and FuzzLang each have one,
  the same deletion-based `err_duplicate_case` repair. This is a one-seed,
  32-example, same-project result and is not yet the paper-level conclusion.
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

### Local-Gemma Compiler-Evidence Campaign

The new synthesis path is now running as a separately archived, **not yet
frozen** experiment. For each target, the largest local model
`google/gemma-4-31B-it` receives TableGen and emission-site evidence plus two
verbatim snippets from clean LLVM production translation units; it proposes a
single FuzzLang DSL Injector rather than editing every output record. Replay
then accepts only a clean parent / failed mutant pair whose primary typed
diagnostic exactly equals the Injector target. No paid API is used.

Thirteen completed campaigns use three clean LLVM production pools (2,213,
2,100, and 2,001 TUs; zero test/test-support paths) built with source
exclusions against the frozen RealSource release, plus one screened Abseil
cross-project input. They archive **974** paired, structurally unique core
records from **21** diagnostics and **258** source TUs (1,045 raw records
before 71 structural duplicates were removed), produced by 23 record-emitting
Injectors. The audit found zero missing `corrected_src` and zero test paths.
The Abseil replay reverified each corrected parent before mutation and retained
125 raw exact-target outputs, providing a first cross-project transfer
measurement. A compiler-replay-feedback retry added 46 raw exact-target unary
diagnostic outputs (43 structurally unique within that campaign) from 27 clean
LLVM production files. Trigger witnesses and compiler feedback are synthesis
evidence only: all retained dataset pairs still come from real clean production
sources. The campaign-level synthesis/replay manifests, record checksums, model
revision, and aggregate audit are pinned in
`data/gen/releases/compiler-evidence-injector-v0/manifest.json` while the JSONL
archives remain outside Git. This is construction evidence only: it is not yet
a merged training release or the matched Injector-versus-DirectEdit result.

The checked-in request builder makes the next queue reproducible from a
TableGen gap list and verified clean production code. Its optional archived
recipe input only retrieves a real syntax shape; no recipe edit is passed to
Gemma or reused as an Injector.

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
16 instances is directional only and is not paper-level evidence. A local
Gemma Base-versus-SFT pilot has now been run on 32 formal eval records, but the
complete matched-token construction-arm comparison has not.

The offline Gemma tokenizer smoke succeeds on short Breadth data: 32/32 and
128/128 prepared examples fit within 4,096 tokens (the 32-example min/median/max
is 241/253/288 tokens). A preliminary RealSource full-TU prefix exposed a real
representation blocker: only 2/32 examples fit, with median 12,624 and maximum
337,379 tokens. Localization addresses the length blocker: the offset edit
exactly round-trips all **2,318/2,318** current RealSource records into the
complete source; localized windows have min/median/p95/max character lengths
170/594/850/1,163, and every rendered native-Gemma offset example fits within
4,096 tokens (min/median/p95/p99/max 201/324/406/452/701). It did not address
learnability: the 876-record, three-epoch offset pilot produced parseable JSON
but **0/32 compiler fixes** on the fixed formal eval slice.

The primary target is now a bounded JSON `corrected_window`, which asks the
model to reproduce the corrected localized code instead of counting character
offsets. It is spliced into the original erroneous translation unit before the
pinned compiler evaluates it. All 876 formal training examples pass the native
Gemma preflight under 1,024 tokens (228/491/878 min/median/max) with no
truncation. This representation must be used consistently across the remaining
matched SFT arms; the offset form remains a recorded representation ablation.

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

Those two infrastructure runs used native chat formatting, the localized
offset target, answer-only loss, BF16, LoRA rank 16, seed 42, and zero implicit
truncation. They validated training and adapter saving, not repair quality.

The 2026-07-20 representation and effectiveness pilots add the missing local
adapter-inference and compiler-verification path:

| arm | train setting | eval denominator | verified fix | exact match |
|---|---:|---:|---:|---:|
| offset overfit diagnostic | 32 records, 10 epochs | 8 training examples | 3/8 | 3/8 |
| window overfit diagnostic | 32 records, 10 epochs | 8 training examples | 5/8 | 5/8 |
| offset SFT | 876 records, 3 epochs | 32 formal eval | 0/32 | 0/32 |
| window Gemma Base | no SFT | 32 formal eval | 5/32 (15.6%) | 0/32 |
| window SFT | 876 records, 3 epochs | 32 formal eval | **20/32 (62.5%)** | **13/32 (40.6%)** |

The window SFT run used 165 optimizer steps, completed in 698.8 seconds, and
ended at train loss 0.03121. This low loss is not itself evidence of repair
quality. On the paired examples there are 15 SFT-only successes, zero base-only
successes, five shared successes, and 12 shared failures. The train
and 32-record eval slice have zero source-TU or record-ID overlap, but both are
from the current LLVM RealSource corpus; unseen-project transfer is not tested.

All 32 base and SFT outputs were parseable. The first evaluation passed
`clang++` for every `__CLANG__` placeholder and made three records from the C
file `llvm/lib/Support/BLAKE3/blake3_dispatch.c` appear stale. The verifier now
selects distinct patched `clang`/`clang++` drivers from the compile language;
model-free revalidation confirms that all 32 corrected sources compile and
changes one exact SFT output from compile-fail to compile-clean. No model output
was regenerated.

Seven SFT fixes and all five base fixes compile without exact-matching the
archived correction. The reproducible gold-aware audit reports edit-size
min/median/max 1/30/64 for the 20 SFT fixes and 2/20/37 for the five base fixes.
It flags **1/20** SFT fixes and **0/5** base fixes: the non-exact
`err_duplicate_case` repair deletes two lines (56 characters), 5.09 times the
gold edit size. No fix is an empty or unexpected large-window deletion. The
flagged case still requires behavioral review; compile-clean alone is not
semantic correctness. SFT responses were 125--264 tokens, below the
512-token base cap and below half of the SFT run's 1,024 cap, so the comparison
is not explained by an SFT truncation advantage.

Adapters, per-instance outputs, summaries, and ignored run manifests are
archived under `.artifacts/`; manifests contain model revision, source-data
SHA-256, adapter SHA-256, configuration, and metrics. A ROCm activation-
checkpoint recomputation error affected the first full window attempt; the
successful run explicitly disabled activation checkpointing and recorded that
choice. No paid API was used. This is a strong single-seed feasibility signal,
not the paper-level matched-token result.

## Main Missing Evidence

The revised paper requires four paper-level results that remain incomplete:

1. **Injector method result:** a matched comparison of FuzzLang DSL Injector
   reuse, transfer, exact-target yield, and cost against direct per-record
   Gemma editing.
2. **Multi-project RealSource result:** scale the successful Abseil transfer
   pilot into a release and add a held-out C project, with coverage and
   provenance isolation.
3. **Gemma SFT result:** expand the completed single-seed, token- and optimizer-
   update-matched Mechanical/DirectEdit/FuzzLang experiment to multiple seeds,
   a larger unseen-TU cohort, and unseen-project sets.
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

### B. Gemma SFT Main Experiment

- preserve the completed canonical-data, native-template, offline tokenizer,
  32/128 preparation path, and strict token preflight;
- use the completed bounded `corrected_window` representation identically
  across matched SFT arms; retain offset edits only as the completed negative
  representation ablation;
- preserve the pinned local training dependencies and the completed Gemma 3 4B
  32/128-record GPU smoke and 876-record pilot paths;
- keep the documented 31B FSDP incompatibility out of the critical path;
- preserve separate C/C++ compiler-driver revalidation in every evaluation;
- preserve the completed 297-record RealSource-Mechanical control and the
  frozen 297-record/144,710-rendered-token strict arms; the earlier short-
  program Mechanical pool remains only a domain-shift ablation;
- rerun the matched-arm experiment with multiple seeds and evaluate on a larger
  unseen-TU cohort plus at least one unseen project;
- preserve matched realized rendered tokens and optimizer-update counts,
  archive completion-token totals separately, and keep TRL sequence packing
  disabled because the available TRL+SDPA path risks cross-sample attention;
- extend the completed static audit with behavioral checks for the flagged
  duplicate-case repair and a tests-based subset;
- run the matched-token construction arms, larger project-isolated evaluation,
  and multiple seeds.

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
