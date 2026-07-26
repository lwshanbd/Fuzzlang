# FuzzLang: Revised Research and Experiment Plan

**Target:** CGO, September 2026
**Compiler version:** `llvmorg-22.1.8` everywhere
**Status date:** 2026-07-22

> **Live campaign note (2026-07-25).** The active expansion criterion is a
> fresh strict FuzzLang Injector audit against the full **3,891** pinned
> TableGen error catalog, with a goal of at least **1,000** verified diagnostic
> types.  The current live audit is 807/3,891.  Historical 1,935-diagnostic
> figures in this plan are a separately scoped paper-analysis denominator and
> must not be used to report live campaign progress.

## 1. Research Positioning

FuzzLang treats the compiler as more than a verifier. The compiler is the most
complete structured source of knowledge about compilation errors: diagnostic
definitions describe the error space, compiler emission sites encode the
semantic conditions that produce each error, regression evidence provides
concrete trigger patterns, and the compiler itself validates every generated
example.

The revised thesis is:

> FuzzLang distills compiler knowledge into reusable, diagnostic-specific
> Injectors, applies those Injectors to correct source code from real projects
> to construct a broad and compiler-verified compilation-error dataset, and
> demonstrates the value of that dataset by fine-tuning an open Gemma model.

The paper makes three primary claims:

1. **Compiler-derived construction.** Compiler diagnostics, emission sites,
   regression evidence, and verifier feedback provide a principled basis for
   constructing compilation-error data.
2. **Reusable generation.** A model can synthesize one reusable Injector per
   diagnostic instead of making one model call per generated record. Replaying
   Injectors on real-project translation units improves coverage and amortizes
   model cost.
3. **Dataset value.** Under matched training-token and inference budgets,
   fine-tuning Gemma on FuzzLang data improves verified repair performance on
   unseen source files, unseen projects, and naturally occurring errors.

The earlier hypothesis that a typed diagnostic observation should outperform
raw compiler stderr is no longer a core claim. Existing results show that the
repair loop is valuable but typed diagnostics and stderr perform similarly for
a strong hosted model. This result may be reported honestly as an exploratory
negative result or appendix analysis. It is not on the critical path.

## 2. Frozen Dataset Taxonomy

The paper must not conflate errors injected into real source code with errors
that occurred naturally in project history. We will use three names throughout
the code, artifacts, experiments, and paper.

### 2.1 FuzzLang-Breadth

Compiler-derived, verifier-checked correct/broken pairs optimized for diagnostic
coverage. Programs may be self-contained rather than extracted from a real
application.

Current baseline:

- 13,745 structurally deduplicated records;
- 1,538/1,935 strict C/C++ code diagnostics covered (79.5%);
- 1,194/1,935 diagnostics covered at multiplicity at least three (61.7%).

This dataset supports the diagnostic-space breadth claim.

### 2.2 FuzzLang-RealSource

Synthetic errors introduced into correct, non-test translation units from real
projects. These are realistic-source injected errors, not naturally occurring
developer mistakes.

Current LLVM baseline:

- 2,318 records;
- 714 observed diagnostic names;
- 702/1,935 strict C/C++ diagnostics covered (36.3%);
- 208 diagnostics covered at multiplicity at least three;
- 847 mutually isolated non-test LLVM source translation units across the
  current base and replay releases.

This dataset supports the realism, Injector transfer, and fine-tuning claims.

### 2.3 NatErr

Naturally occurring compilation errors reconstructed from real project commit
history. A formal NatErr record must contain the failing source, corrected
source recovered from the fix, exact diagnostic, build command, project and
commit provenance, and verifier evidence.

The current LLVM Stage-2 output has 86 reproduced failing files from 75
candidates, but it is not yet a formal paired release. NatErr is an external
validity set, not the source of the paper's scale claim.

### 2.4 Invariants for Every Core Record

- The corrected source compiles under its recorded command.
- The erroneous source fails and carries the compiler-observed diagnostic.
- `corrected_src` is mandatory.
- Clang/LLVM regression tests and test-support code are never final records.
- Compiler tests may be used only as evidence for understanding a diagnostic.
- Every generated record stores the responsible Injector or generation method.
- Deduplication is structural, not merely textual.
- Project, source-TU, and Injector leakage are audited for every split.

## 3. Terminology and Method

An **Injector** is one diagnostic-specific transformation program. **FuzzLang
DSL** is the constrained language used to represent and execute Injectors.

The intended pipeline is:

```text
TableGen diagnostic + compiler emission site + regression evidence
                              |
                              v
                    Gemma synthesizes Injector
                              |
                              v
              FuzzLang DSL matcher and transformation
                              |
                              v
                correct real-project source code
                              |
                              v
             patched Clang validation and feedback
                              |
                              v
                    accepted paired Record
```

Gemma should normally be invoked once to synthesize or repair an Injector, not
once per output record. The same accepted Injector can then be replayed on many
translation units and projects.

## 4. FuzzLang DSL: Deliberately Narrow Scope

FuzzLang DSL must not become a general-purpose source transformation language
on the paper's critical path. Version 0 formalizes the capabilities already
demonstrated by the recipe replay system.

### 4.1 Required v0 Features

- diagnostic name and optional diagnostic ID;
- C or C++ language constraint;
- exact token patterns;
- identifier metavariables and repeated-identifier equality constraints;
- numeric placeholders;
- bounded left and right lexical context;
- `insert`, `delete`, and `replace` operations;
- literal and bound-variable replacement parts;
- single-location edits;
- maximum edit length, candidate count, and verification limits;
- provenance, exemplar IDs, support count, and schema version;
- deterministic serialization, hashing, replay, and backward compatibility
  with existing v1/v2 recipes.

### 4.2 Controlled v1 Expansion

Version 1 retains the v0 single-site lexical model and adds only two
evidence-backed capabilities:

- payload-local identifiers are rendered as deterministic, collision-free
  fresh names and may be reused within the replacement payload;
- byte-exact intra-token edits may be expanded to complete token boundaries
  when reconstructing the original erroneous source proves equivalence.

Both capabilities are opt-in at extraction time, remain subject to the same
edit/candidate/verification limits, and preserve parsing of archived v0
Injectors. Literal string/comment payloads have a separate experimental flag;
they are not part of the main v1 method until held-out transfer justifies them.

### 4.3 Explicit Non-Goals

- a general AST query language;
- arbitrary type inference;
- a general symbol-table language;
- arbitrary generated Python execution;
- unrestricted multi-site transformations;
- completeness over all C/C++ diagnostics.

Only evidence-backed primitives may be added after v0. For example, a narrowly
defined same-scope declaration selector may be added if a measured diagnostic
gap cannot be reached otherwise. General AST/type/scope support is deferred
until after the main dataset and SFT results exist.

### 4.4 Hybrid Fallback

FuzzLang uses a hybrid generation policy:

1. replay a FuzzLang DSL Injector when the diagnostic is expressible;
2. use a Gemma direct edit for an otherwise unreachable long-tail case;
3. validate the direct edit with patched Clang;
4. attempt to distill successful direct-edit pairs into a new Injector;
5. retain the verified pair even if distillation fails, with its method label.

This fallback prevents DSL engineering from blocking data production or SFT.

## 5. Parallel Week-1 Workstreams

Three independent workstreams start immediately.

### 5.1 Freeze Data and Evaluation Definitions

- implement and document the Breadth/RealSource/NatErr release boundaries;
- freeze the strict 1,935-diagnostic denominator;
- define project-, TU-, and Injector-isolated splits;
- audit all current RealSource releases for test/test-support contamination;
- define a final release manifest schema and checksum policy;
- record generation method and Injector ID on every record;
- produce a single reproducible coverage command for each data tier.

### 5.2 Gemma SFT Smoke Test

The existing Tioga setup demonstrates high-throughput Gemma-4-31B inference.
The SFT driver accepts canonical FuzzLang records, uses the native Gemma chat
template, performs an offline tokenizer preflight, and trains only on the
assistant repair rather than charging loss to the prompt. The first goal
remains functional validation, not a full training run.

Tasks:

1. convert canonical `Record` objects into diagnostic repair examples;
2. use the native Gemma chat template;
3. run a real-tokenizer length preflight and reject silent truncation by
   default;
4. use a deterministic localized source window and reconstruct every model
   answer into the complete translation unit before verification. The primary
   target is a JSON `corrected_window`; retain the offset-based relative edit
   as a representation ablation. Require exact round-trip for gold targets and
   use the same chosen representation across matched SFT arms;
5. establish multi-GPU LoRA training on the eight MI250X GCDs, using an
   appropriate distributed strategy rather than inference-style
   `device_map="auto"`;
6. train on 32 examples, then 128 examples;
7. verify finite/decreasing loss, adapter saving and loading, and valid output;
8. reload the adapter into local inference and run compiler-verified repair on
   a fixed smoke set; endpoint serving is an engineering optimization, not a
   scientific gate;
9. scale to approximately 1,000 training examples only after the pipeline is
   stable.

Whole real-project translation units are expected to exceed a 4K-token context
frequently. Truncating a full-file prompt or answer can remove the diagnostic or
the repair itself, so overlength handling remains explicit and measured. The
offset-based localized representation retains all 2,318 RealSource records,
round-trips exactly, and puts every rendered example below 4,096 Gemma tokens
(maximum 701), but a controlled pilot showed that exact character offsets are
poor targets for held-out generation. The bounded `corrected_window` target is
therefore the primary representation. On the 876-record formal training split,
all 876 examples fit below 1,024 tokens (228/491/878 min/median/max) with zero
truncation. Every generated window is spliced into the original full source and
the resulting translation unit is verified by the pinned compiler.

If 31B LoRA training is not stable within the time gate, use a smaller model
from the same Gemma family for SFT while retaining Gemma-4-31B for local
inference experiments. This remains an all-Gemma, zero-paid-API pipeline.

Execution snapshot (2026-07-19): the 31B path reached correct text-only LoRA
attachment (122,429,440 trainable parameters), but FSDP1 stalled during model
preparation on Tioga's 4.18 kernel and FSDP2 failed in
`accelerate==1.14.0` while treating a PEFT parameter as a DTensor
(`Tensor.device_mesh`). The time gate was therefore enforced. The fallback
`google/gemma-3-4b-it` revision
`093f9f388b31de276ce2de164bdc2081324b9767` completed a 32-record/one-step
LoRA smoke and a 128-record/two-step smoke, saving both adapters. The 128-record
run had zero overlength examples (202/337.5/702 min/median/max tokens); loss
fell from 5.600 to 2.889 and mean token accuracy rose from 0.5105 to 0.6703.
These were bounded infrastructure smokes rather than paper-level SFT results.

Execution snapshot (2026-07-20): adapter reload and compiler-verified local
evaluation now work. A matched 32-record, 10-epoch training-set diagnostic
reached 3/8 exact compiler fixes with the offset representation and 5/8 with
`corrected_window`. The formal 876-record, three-epoch offset pilot then
produced 0/32 fixes on a fixed 32-record held-out slice. With all
other data/model/optimizer choices held fixed, the `corrected_window` pilot
trained for 165 optimizer steps in 698.8 seconds and reached 20/32 compiler
fixes (62.5%) and 13/32 exact matches (40.6%). The unfine-tuned Gemma base
reached 5/32 compiler fixes (15.6%) and 0 exact matches on the same examples: a
+46.9-point paired pilot gain, with 15 SFT-only successes, no base-only
success, five successes shared by both, and 12 shared failures.

The first evaluation incorrectly used `clang++` for every `__CLANG__`
placeholder and made three records from one C translation unit appear stale.
The verifier now accepts distinct patched C and C++ drivers, and model-free
revalidation of all archived outputs confirms that all 32 corrected sources
compile. No generated response changed.

All 32 outputs in both arms were parseable. The SFT outputs were 125--264
tokens, so its 1,024-token ceiling never bound; the base was capped at 512,
which still exceeds twice the largest 247-token gold target. The 876-record
run required activation checkpointing to be disabled after a reproducible
ROCm recomputation-metadata failure; this stability choice is recorded in the
run manifest and did not change the experimental data or LoRA recipe. These
single-seed, small-slice results close the local training/inference pipeline
gate. A gold-aware static audit flags 1/20 SFT compiler fixes (a non-exact
duplicate-case repair that deletes two lines) and 0/5 base fixes for unexpected
line deletion or an edit over five times the gold size. That case still needs
behavioral review. This remains a pilot, not the final matched-token multi-arm
E3 result.

The local Gemma README currently contains a plaintext access credential. It
must be removed from documentation, moved to an environment/secret mechanism,
and rotated before artifact preparation.

### 5.3 FuzzLang DSL v1

- define the v0 schema and parser;
- convert all existing portable recipes into versioned Injectors;
- preserve recipe JSON compatibility;
- add deterministic replay and round-trip tests;
- attach Injector IDs to generated records;
- replay on unseen, non-test LLVM translation units;
- test the same Injectors on at least one non-LLVM C++ project.

Execution snapshot (2026-07-19): all 594 portable recipes round-trip through
FuzzLang DSL v0. The replay CLI emits canonical Injector artifacts and embeds
Injector IDs in record provenance. A zero-API LLVM pilot produced 30 records;
formal two-sided revalidation retained all 30 from 11 held-out non-test TUs,
covering 27 observed diagnostics. Seventeen records (56.7%) hit the requested
target exactly, spanning 16 diagnostics. A second run used an exact-only,
one-record-per-diagnostic diversity cap and produced 70 additional records for
70 distinct targets from 43 new non-test TUs. Formal revalidation retained all
70 with no overlap or structural duplicate against the preceding 2,348
records. No paid API was used in either run.

The controlled v1 extraction expands 594 portable recipes spanning 306
diagnostics to 1,239 recipes spanning 598 diagnostics. In a matched LLVM run,
the 594-recipe baseline required 91 TUs and 436 mutant compilations to reach
100 exact targets, whereas v1 required 64 TUs and 393 compilations. Formal
revalidation retained 99 baseline-arm records and 100/100 v1-arm records; v1
reached 44 diagnostics outside the old portable diagnostic space. Both arms
use zero test sources and have no
source overlap with earlier releases. The more permissive 1,321-recipe literal
variant remains experimental.

The matched transfer run on held-out Abseil revision
`1e6d60b2ca9356542fe62b73ab010424aa2796cf` used 120 clean, non-test C++ TUs
and identical seed and replay caps. The 594-recipe arm scanned all 120 TUs,
used 763 mutant compilations, and formally retained 97/97 exact-target records
from 64 sources. The 1,239-recipe arm reached its 100-diagnostic cap after 71
TUs and 548 mutant compilations; formal revalidation retained 100/100 records
from 51 sources. Forty-six target diagnostics are outside the original
306-diagnostic portable space, and 55 records are backed by a fresh-name
Injector. Both arms have zero test/test-support paths, zero structural
duplicates, and project-relative `abseil:absl/...` provenance.

## 6. Week-2 Gates and Fallback Decisions

### 6.1 FuzzLang DSL Gate

By the end of Week 2, v0 should:

- represent and round-trip all 594 currently portable recipes;
- preserve identifier-binding semantics and safety limits;
- produce exact-target records for at least 50 distinct diagnostics on held-out
  source translation units;
- achieve at least a 25% exact-target share among accepted pilot records;
- successfully replay at least a non-trivial subset on a second C++ project;
- require no paid API calls.

If the gate passes, add at most one narrowly scoped type/scope-aware primitive
before the main experiment. If it fails, freeze v0 and proceed with the proven
recipe-v2 plus Gemma direct-edit hybrid. No general DSL redesign is allowed on
the critical path.

The unfiltered 30-record pilot passes the acceptance and exact-target-share
checks, the 70-diagnostic diversity run passes the LLVM-side distinct-target
threshold, and the matched v1 experiment shows a larger reachable diagnostic
space with lower TU and compiler-invocation cost at the 100-diagnostic cap.
The matched Abseil replay demonstrates non-trivial second-project transfer and
adds 46 exact-target diagnostics outside the original portable space. The
FuzzLang DSL gate therefore passes. No broader DSL redesign is authorized on
the critical path; the next method work is Gemma Injector synthesis and the
matched Injector-versus-direct-edit experiment.

Execution snapshot (2026-07-22): the offline `google/gemma-4-31B-it`
compiler-evidence loop has synthesized and replayed 23 record-emitting
Injectors on three clean, test-free LLVM production pools (2,213, 2,100, and
2,001 TUs) that exclude frozen-RealSource overlaps, with a first screened
Abseil cross-project replay. Thirteen archived campaigns yielded 974
structurally unique paired records (1,045 raw before structural deduplication)
across 21 diagnostics and 258 source TUs; each accepted record has
`corrected_src` and an exact primary diagnostic match, and the audit found zero
test paths. A compiler-replay-feedback retry contributed 46 raw exact-target
outputs (43 structurally unique within the campaign), demonstrating that
compiler evidence can improve a reusable Injector after its first replay.
Trigger witnesses and replay feedback are synthesis evidence only; retained
data still originates solely from real clean LLVM production code. The archive
manifest pins every synthesis/replay manifest and checksum. This is an
in-progress construction result, not an E1 comparison: the matched DirectEdit
arm and cross-project replay of these synthesized Injectors remain required.

For reproducible gap-driven queue construction, `run_build_requests.py` now
filters a TableGen gap list, retrieves two matching snippets from verified,
non-test production TUs, and resolves the pinned compiler's diagnostic IDs.
Archived recipes are retrieval-only feasibility seeds: their edits are never
placed in the model prompt and never copied into a synthesized Injector.

### 6.2 Gemma SFT Gate

By the end of Week 2, the training path should:

- complete a 128-example LoRA run;
- report tokenizer-length statistics with zero implicit truncation;
- round-trip the chosen RealSource edit/patch representation back to a
  compiler-verifiable complete source file;
- save and reload an adapter;
- reload the adapter through local inference (directly or through an endpoint);
- emit a parseable bounded repair object and reconstruct a complete source;
- complete a fixed compiler-verified evaluation without infrastructure errors;
- archive configuration, logs, model revision, and random seed.

If the 31B path fails the gate, immediately switch the SFT experiment to a
smaller Gemma-family checkpoint rather than spending the remaining schedule on
distributed-training infrastructure.

Current status (2026-07-20): this fallback has been taken and the bounded
training/inference path has passed. Gemma 3 4B completed the 32/128-record
infrastructure smokes, the 32-record representation diagnostic, and the
876-record three-epoch pilot.
Adapters reload in a separate process, all evaluated answers were parseable,
and the driver-correct fixed compiler slice improved from 5/32 fixes for the
base model to 20/32 after SFT. The remaining work is the paper experiment:
matched-token construction arms, larger and project-isolated evaluation,
multiple seeds, and behavior/NatErr checks.

## 7. Core Experiment E1: Injector Versus Direct Edit

This is the highest-priority method experiment. It directly tests whether
reusable Injector synthesis is better than making a model call for every
record.

### 7.1 Protocol

- Select 100--200 strict C/C++ diagnostics, stratified by Sema/Parse/Lex and by
  current coverage.
- Use the same fixed pool of clean, non-test real-project translation units.
- Use the same local Gemma checkpoint and compiler evidence.
- Apply the same patched Clang verifier and diagnostic-target acceptance rule.
- Match wall-clock/GPU budgets where possible and record actual model output
  tokens and compiler invocations.
- Cap records per diagnostic, source TU, and project before deduplication.

### 7.2 Arms

1. generic mechanical mutation without diagnostic-specific compiler evidence;
2. Gemma direct edit, with a model invocation per attempted record;
3. Gemma-synthesized FuzzLang DSL Injector, amortized over many sources;
4. the hybrid policy: Injector first, direct edit for the unresolved tail.

An optional evidence ablation, if time permits, compares diagnostic
name/template alone against name/template plus emission site and regression
evidence.

### 7.3 Metrics

- exact-target rate per attempted and per accepted candidate;
- verified records and structurally unique records;
- new `coverage@1` and `coverage@3` diagnostics;
- effective records per target diagnostic;
- records per model output token and per GPU hour;
- compiler invocations per accepted record;
- Injector synthesis/repair cost and amortization curve;
- transfer rate across unseen TUs and unseen projects;
- number of sources and projects reached per Injector;
- failure categories: not applicable, clean mutant, wrong diagnostic, timeout,
  unsafe/oversized edit, and source compilation failure.

The expected Injector advantage is amortized efficiency and transfer, not
necessarily the highest first-attempt success rate.

## 8. Core Experiment E2: Multi-Project RealSource Expansion

LLVM remains the main C++ training source, but an LLVM-only result cannot prove
cross-project transfer and is approaching diminishing diagnostic returns.

### 8.1 Candidate Projects

Run a short build-feasibility screen before fixing the final list. Prefer
projects with a reproducible build, a usable `compile_commands.json`, and many
non-test translation units.

- LLVM: main C++ training source;
- DuckDB: manageable CMake-based real C++ application;
- Abseil or fmt: template-heavy C++ transfer source;
- curl: CMake-supported C project for C-family diagnostics;
- FFmpeg/PostgreSQL: optional later C expansion, not an initial dependency.

Qt and dependency-heavy projects are considered only if their build setup is
already reliable. A project is dropped if it cannot provide a stable compile
database and a high clean-baseline rate within two engineering days.

### 8.2 Isolation

- training projects and final held-out projects must be disjoint;
- no source TU may straddle train/dev/eval;
- final evaluation must include at least one entirely unseen project;
- report both seen-diagnostic/unseen-source and unseen-diagnostic slices;
- compiler tests, project tests, examples, benchmarks, fuzzers, and test support
  remain excluded from RealSource.

### 8.3 Targets

Targets are goals, not release claims:

- 10,000--30,000 structurally deduplicated RealSource records;
- at least three real projects represented;
- approximately 1,000/1,935 strict diagnostics covered in RealSource;
- 350--400 diagnostics at multiplicity at least three as the core goal;
- 600 diagnostics at multiplicity three only as a stretch goal.

Multiplicity should arise from successful Injector transfer across distinct
sources, not from flooding one diagnostic or TU. Coverage and multiplicity
curves will be reported as functions of records, Injectors, and projects.

Execution snapshot (2026-07-19): Abseil passes the build-feasibility and
cross-project transfer screen with 159/159 clean non-test library TUs. The
matched v0/v1 experiment above is transfer evidence, but its 100 records remain
an experiment rather than a merged RealSource release. Abseil is therefore a
viable C++ project for E2; a C-family project and release-scale generation are
still required.

## 9. Core Experiment E3: Gemma Fine-Tuning Value

The primary downstream evidence is Gemma repair before and after SFT. The
experiment must separate the value of FuzzLang data from the trivial effect of
seeing more training tokens.

### 9.1 Main Arms

1. **Gemma Base:** no fine-tuning;
2. **Mechanical-SFT:** simple mechanical-mutation records;
3. **DirectEdit-SFT:** real-source records generated by per-record model edits;
4. **FuzzLang-SFT:** real-source records generated by FuzzLang DSL Injectors;
5. **Full-SFT (optional):** Breadth plus RealSource.

The SFT arms use the same base checkpoint, LoRA configuration, optimizer,
training-token budget, repair representation, source/project split policy, and
evaluation budget. No arm may silently discard or truncate overlength examples.
The primary controlled table also matches optimizer-update count. The preferred
construction is to match both rendered tokens and record count, then use the
same batch size and epochs; a token-aware batch sampler is an acceptable
fallback only if its realized token and update counts are archived. Report
loss-bearing completion tokens separately from complete rendered tokens.
Report both:

- an equal-training-token comparison measuring end-to-end dataset utility; and
- a matched-diagnostic subset comparison isolating construction quality from
  diagnostic coverage.

Pilot signal (2026-07-20): one RealSource arm on a fixed 32-example slice
improved verified Fix@1 from 5/32 for Gemma Base to 20/32 after SFT.
This establishes that the local data-to-adapter-to-compiler path can show a
large paired gain, but it does not replace the arms above: it has one seed, a
small same-project slice, no matched-token construction baselines, and no
behavioral test column.

Data-arm snapshot (2026-07-20): the RealSource-Mechanical gate has passed. The
bounded scale run scanned 250 unique LLVM sources and issued 810 compiler
invocations: 250 clean-baseline checks and 560 mutant checks. It produced 494
verified pairs before global retention caps and retained 297 records spanning
59 diagnostics. At least one verified mutant was produced for 248 of the 250
sources. The retained set has zero test/test-support sources, zero missing
`corrected_src`, and zero API calls. Its records file has SHA-256
`ae12cdd2cadeaff96d857550312faf7691840a46dc8b523cb357c60a44e3a2ab`.
Measured alone against the 3,489-diagnostic code-only denominator, it covers 59
diagnostics and reaches multiplicity three for 27. Seven diagnostic names were
new relative to the existing RealSource plus recipe-replay pools.

The strict three-arm builder now freezes **297 records and 144,710 complete
rendered Gemma tokens per arm**. The realized loss-bearing completion-token
totals are 58,907 Mechanical, 57,372 DirectEdit, and 57,564 FuzzLang. The arms
cover 59/183/150 diagnostics and 240/164/222 source TUs, respectively; the
FuzzLang arm contains 131 distinct Injector IDs. All eval-leakage checks are
zero. Cross-arm exact localized-input, corrected/erroneous-pair, and record-ID
overlap are also zero. The arms intentionally share 124 source TUs: this keeps
the real-project source domain partially controlled while comparing different
error-construction methods, and is reported explicitly rather than described
as provenance isolation. Final evaluation remains source-disjoint from all
three training arms.

The data gate is therefore complete. All three
matched arms completed three epochs and 57 optimizer steps with the same
memory-safe `batch_size=1`, gradient accumulation 2 configuration. Mechanical,
DirectEdit, and FuzzLang train losses were 0.03362, 0.05672, and 0.03799; these
are audit values, not repair-quality evidence. The first attempt exposed a
node ECC failure and a longest-batch OOM, after which all arms were restarted
under the same configuration. On the fixed 32-example LLVM eval cohort, with
all corrected sources revalidated and a common 512-token inference cap, the
initial matched-arm result is:

| Arm | Verified Fix@1 | Exact match | Degenerate compiler fixes |
|---|---:|---:|---:|
| Gemma Base | 5/32 (15.6%) | 0/32 | 0/5 |
| Mechanical-SFT | 5/32 (15.6%) | 1/32 (3.1%) | 0/5 |
| DirectEdit-SFT | 15/32 (46.9%) | 6/32 (18.8%) | 1/15 |
| FuzzLang-SFT | 16/32 (50.0%) | 11/32 (34.4%) | 1/16 |

FuzzLang and DirectEdit share 13 compiler fixes; FuzzLang has three unique
fixes and DirectEdit two. Their compile-rate difference is therefore only one
example and must not be presented as superiority. Exact matches are more
directional: all six DirectEdit exact matches are shared, with five additional
FuzzLang exact matches. The same `err_duplicate_case` line-deletion repair is
the compiler-clean quality flag in both arms. This single-seed same-project
slice is encouraging evidence, not the paper-level result; it still needs
multiple seeds, a larger cohort, unseen projects, and behavior checks. TRL sequence packing remains
disabled: the available TRL+SDPA path carries a cross-sample-attention risk,
so the aborted packing smoke is excluded and all frozen arms train unpacked.

### 9.2 Evaluation Columns

- unseen TUs from known projects;
- an entirely unseen project;
- seen diagnostics expressed through unseen code structures/Injectors;
- a diagnostic-tail slice;
- formal NatErr natural failures;
- single-diagnostic and cascade-heavy failures.

### 9.3 Metrics and Statistical Protocol

- verified Fix@1 and Fix@k;
- micro and per-diagnostic macro fix rate;
- per-family and per-project fix rate;
- model output tokens, attempts, and wall time;
- edit distance and changed-line count;
- large-deletion and degenerate-repair rate;
- diagnostic disappearance and replacement by a different error;
- project test/build success on a feasible audited subset;
- three random seeds for main SFT/evaluation cells where feasible;
- bootstrap confidence intervals and paired confidence intervals for method
  differences.

A compile-clean output alone is insufficient evidence of a useful repair if it
deletes functionality. Minimality and behavior-preservation audits are required.

## 10. Core Experiment E4: NatErr External Validity

NatErr does not need thousands of records. Its purpose is to show that the
model trained on FuzzLang-generated data transfers to failures that FuzzLang did
not create.

Tasks:

1. recover corrected source from every retained fix commit;
2. remove test/test-support and build-system-only cases;
3. compile the corrected and failing versions under recorded commands;
4. require a stable primary diagnostic;
5. convert accepted pairs to canonical `Record` objects;
6. structurally deduplicate and archive provenance;
7. add one or two buildable projects beyond LLVM;
8. use project and/or temporal isolation from all SFT data.

The formalization code and rejection accounting are now implemented. An
initial three-candidate LLVM smoke was blocked by the shallow sparse history in
`external/llvm-project` and by stale Stage-2 build paths/generated headers. The
next operational prerequisite is a full historical checkout plus a relocatable
or reconstructed compile environment; lowering the pairing or no-test gates is
not an acceptable workaround.

Core target: 100--300 high-quality natural errors from two or three projects.
Report candidate-mining yield, reproduction yield, rejection reasons, and
confidence intervals honestly.

An optional continual-learning experiment trains on earlier NatErr failures and
tests on temporally later failures. This is secondary to the base-versus-SFT
external-validity comparison.

## 11. Quality, Reproducibility, and Artifact Requirements

- one pinned compiler revision and patched binary provenance;
- versioned FuzzLang DSL schema and immutable Injector IDs;
- archived Injectors, generated records, rejection logs, and manifests;
- checksums and archive integrity checks;
- exact model snapshot, container, LoRA configuration, seeds, and prompts;
- complete compiler command provenance;
- coverage reports reproducible from released records;
- a stratified manual audit of at least 100 records;
- source/project leakage audit;
- test/test-support exclusion audit;
- accepted/rejected candidate funnels for every generation method;
- no paid API dependency in the final reproducible pipeline.

## 12. Six-Week Execution Schedule

### Week 1: De-risk in Parallel

- freeze dataset definitions and evaluation protocol;
- complete Gemma 32/128-example SFT smoke;
- preserve FuzzLang DSL v0 compatibility and complete the controlled v1
  fresh-name/token-normalization expansion;
- begin build-feasibility screening for new projects.

### Week 2: Gates and Core Pilot

- enforce the FuzzLang DSL and Gemma SFT gates;
- freeze or fall back immediately when a gate fails;
- run the first matched Injector-versus-direct-edit pilot;
- select the final multi-project source pool.

### Week 3: RealSource Expansion

- run Injectors and hybrid generation across selected projects;
- measure transfer, exact-target yield, coverage, multiplicity, and efficiency;
- freeze the candidate main training release.

### Week 4: Main Gemma SFT

- run equal-token SFT arms;
- run fixed held-out evaluations;
- inspect failure modes before launching all seeds;
- freeze model and training configurations.

### Week 5: Main Evaluation and NatErr

- complete remaining seeds and ablations;
- finalize NatErr paired records;
- run unseen-project and NatErr evaluations;
- conduct minimality and behavior-preservation audits.

### Week 6: Analysis and Artifact

- aggregate confidence intervals and coverage curves;
- produce per-family, per-project, and cost analyses;
- archive datasets, Injectors, adapters, logs, and manifests;
- write the paper around the frozen claims and completed evidence.

## 13. Critical Results Required for Submission

The paper is ready only when these four results exist:

1. a matched comparison showing the reuse, transfer, and cost behavior of
   FuzzLang DSL Injectors versus direct per-record editing;
2. a multi-project RealSource dataset with measured diagnostic coverage and
   provenance isolation;
3. a matched-token Gemma SFT result demonstrating the value of FuzzLang data;
4. an external-validity result on a smaller, formal NatErr set.

## 14. Explicit Stop/Deprioritization Rules

- Do not build a general AST transformation language before the main SFT result.
- Do not let FuzzLang DSL work delay the Gemma SFT smoke or main dataset.
- Do not run additional paid-API repair sweeps.
- Do not spend the main schedule forcing NatErr to become a large dataset.
- Do not count compiler/project tests as RealSource records.
- Do not raise multiplicity by allowing one source or generic failure to flood
  the dataset.
- Do not claim that typed diagnostics outperform stderr without new evidence.
- Do not claim behaviorally correct repair from compile success alone.

These rules preserve a complete fallback paper: compiler-derived high-coverage
data, a narrow reusable Injector artifact, and a controlled Gemma SFT result,
even if advanced FuzzLang DSL features or large-scale NatErr reproduction do
not mature before the deadline.
