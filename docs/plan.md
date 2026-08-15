# FuzzLang: Revised Research and Experiment Plan

**Target:** CGO, September 2026
**Compiler version:** `llvmorg-22.1.8` everywhere
**Status date:** 2026-08-07

> **Coverage and freeze note (2026-08-07, superseded 2026-08-12).** The paper
> headline is the frozen **1,935-diagnostic strict C/C++ code** denominator.
>
> **Quote `1,208 / 1,935` (62.4%), strict rule**, from the release-union audit
> in `data/reports/strict-coverage-20260812-release-union/`. It is the canonical
> batch-6 campaign audit plus the multi-project library replay (E1), folded in
> under explicit labels by one command, with all 1,977 inputs checksummed. All
> 15,097 E1 records enter with zero rejections under the unchanged admission
> gate.
>
> Folding E1 in moved the strict count from **1,195 → 1,208 (+13)** while the
> inclusive count stayed at **1,242**. That is the informative part: those 13
> types were previously reached *only* by records whose target had been
> relabelled to whatever error fired, and the real-source replay reached them
> **on target**. Paper-scope types that depend on relabelling alone fall from
> **47 to 34**. Applying the library to source it has never seen both extends
> and hardens coverage.
>
> The 08-07 canonical audit remains the authority for the batch-6 lineage in
> isolation (1,195 / +214 strict, 1,242 / +213 inclusive) and for why the
> superseded `batch0053` (1,200 / +171) and live `batch0074` (1,241 / +212)
> audits disagreed — each enumerated a different subset of the same completed
> campaigns.
>
> **Four coverage figures circulate; never add or substitute them.** 1,208 =
> everything released, strict gate (headline). 1,242 = same inputs, relabelling
> allowed. 459 = what one capped real-source pass realizes
> (`data/reports/e1-construction-20260812-devendored/`). 1,538 = the historical
> FuzzLang-Breadth composite, which predates the strict gate and draws on a
> different input union — **not** the paper's coverage claim.

### Immediate execution decision

Do **not** start further broad Injector-generation campaigns. Let already
submitted target-only synthesis and replay chains complete, then run one
canonical strict union audit.

1. If the union reaches **1,329 / 1,935** (the +300 goal), freeze the Injector
   library and training data.
2. If it falls short, generate only the exact remaining diagnostic gaps needed
   to reach that threshold; do not open new exploratory breadth queues.
3. Once frozen, shift the primary compute budget to the experiments below:
   E1 (multi-project construction and cost; E2 merged in), E3 (matched-budget
   SFT plus unseen-project generalization), and E4 (NatErr).

Before any paper table is finalized, publish a release manifest that maps each
reported diagnostic to its Injector IDs, accepted paired records, campaigns,
and source projects. This is required to reconcile the historical Breadth
summary with the current goal audit.

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

This dataset supports the diagnostic-space breadth claim. **Its 1,538 figure
predates the strict admission gate and uses a different input union, so it is
not the paper's coverage headline** — that is 1,208/1,935 from
`data/reports/strict-coverage-20260812-release-union/`.

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
the critical path; the next work is the multi-project zero-cost replay
measurement (E1) and the matched-budget SFT result (E3).

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
in-progress construction result: a released multi-project replay measurement of
these Injectors, at zero GPU and token cost, remains required.

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

## 7. Core Experiment E1: Multi-Project Dataset Construction at Near-Zero Cost

*(E2 was merged into E1 on 2026-08-08; §8 is retained as a pointer.)*

> **Framing correction (2026-08-08).** E1 was previously written as "Injector
> versus Direct Edit", a head-to-head contest between the FuzzLang Injector and
> a large language model at *generating* errors. That framing is retired. It
> asks the wrong question and invites a meaningless answer: a 31B model given a
> concrete file and a concrete target will of course beat a deliberately narrow
> lexical rewriting tool at first-attempt success. FuzzLang's claim was never
> "our tool is smarter than an LLM."
>
> FuzzLang is an **offline tool with near-zero marginal cost**: point it at
> correct source code and it produces compiler-verified errors across a wide
> range of diagnostics, using **no GPU and no model tokens**. Its value is
> established by (a) the breadth and diversity of the dataset it constructs and
> (b) whether fine-tuning on that dataset improves repair, including on projects
> the dataset never saw. Those are E1 and E3 respectively.
>
> A model-based generator is therefore **not a rival to beat at generation
> time**. It appears in this plan in exactly one place where it is meaningful:
> as a *training-data construction baseline* inside E3, answering "does an equal
> budget of FuzzLang-built data train a better repair model than an equal budget
> of LLM-built data?" See §9.
>
> The retired head-to-head and the reason it was withdrawn are recorded in
> `docs/E1-dataset-construction.md` so the result is not re-derived or cited as
> evidence against FuzzLang.

E1 characterizes what the FuzzLang Injector library produces when it is applied
to correct real-project source, and what that costs.

### 7.1 Protocol

- Fix the released Injector library and its version; record its ID set.
- Fix a pool of clean, non-test real-project translation units per project.
- Replay the library with the pinned patched Clang. **No model call is made and
  none is permitted**; a run that needs one is a bug, not a result.
- Apply the same acceptance rule used everywhere: clean parent, failing mutant,
  primary typed diagnostic exactly equal to the Injector's declared target
  (name and DiagID), `corrected_src` retained, no test/test-support source.
- Cap records per diagnostic, per source TU, and per project before structural
  deduplication so one Injector or one file cannot flood the dataset.

### 7.2 Reported quantities

Construction reach:

- strict diagnostic coverage and multiplicity, per project and unioned;
- structurally unique records; distinct source TUs and projects reached;
- sources and projects reached per Injector (the amortization curve);
- yield on translation units and on **projects the library never saw**.

Construction cost:

- GPU hours and model tokens consumed: **zero for library replay**, by design;
- compiler invocations per accepted record, and wall-clock per 1,000 records;
- the one-off cost already sunk in building the library, reported separately
  and honestly, so replay cost and construction cost are never conflated.

Failure categories, so the tool's limits are visible: Injector does not match
the source, clean mutant, wrong diagnostic, timeout, oversized edit, parent
does not compile.

### 7.3 The cost statement the paper makes

The claim is a cost/reach statement, not a quality contest:

> Applying the released Injector library to a previously unseen project
> produces N compiler-verified paired records over K diagnostics using zero GPU
> hours and zero model tokens.

Existing zero-API evidence already supports the shape of this claim: 896
retained records on 428 unseen LLVM TUs, and 97--100 exact-target records from
51--64 sources on held-out Abseil, all with no model or API call. E1 turns that
into a released, multi-project measurement.

Where a per-record model generator is measured at all, it is measured only to
price the alternative (GPU hours and tokens for an equal number of accepted
records), never to declare a winner at error generation.

### 7.4 Projects

Run a short build-feasibility screen before fixing the final list. Prefer
projects with a reproducible build, a usable `compile_commands.json`, and many
non-test translation units.

- LLVM: main C++ training source;
- Abseil: template-heavy C++, build-screened, 159/159 clean non-test library TUs;
- FFmpeg: C-family source, 2,131 clean-gated production TUs already available;
- DuckDB / fmt / curl: further candidates if a third training project is needed.

Qt and dependency-heavy projects are considered only if their build setup is
already reliable. A project is dropped if it cannot provide a stable compile
database and a high clean-baseline rate within two engineering days.

### 7.5 Split and holdout discipline (decided before generation)

The dataset artifact and the SFT training set are **different sizes and must not
be confused**. The artifact target below is a release goal; the SFT training set
is a deliberately small matched-budget subset of it (§9). Nothing is "used up"
by training — the risk is leakage, not exhaustion.

Holdout is frozen **before** any record is generated, and every record is
labelled with its split at creation time:

- at least one project is **fully held out** and contributes no training record
  at any stage; it exists only as the unseen-project evaluation column;
- inside every training project, a fixed fraction of translation units is
  reserved as the unseen-TU evaluation column before generation begins;
- no source TU may straddle train/dev/eval, and no Injector ID may produce
  records on both sides of a split without being recorded as shared;
- NatErr (E4) is never trained on;
- compiler tests, project tests, examples, benchmarks, fuzzers, and test support
  are excluded from RealSource entirely.

A generation run that would emit a record from a held-out TU or a held-out
project must fail loudly rather than silently relabel it.

### 7.6 Release targets

Targets are goals, not release claims, and describe the **artifact**, not the
training set:

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
matched v0/v1 experiment is transfer evidence, but its 100 records remain an
experiment rather than a merged RealSource release. A C-family project and
release-scale generation are still required.

## 8. Core Experiment E2: merged into E1

E2 ("Multi-Project RealSource Expansion") was merged into E1 on 2026-08-08.
Once E1 was reframed from a method contest into a multi-project
construction-and-cost measurement, the two asked the same question. Its project
list, isolation rules, and release targets now live in §7.4--§7.6. The section
number is retained so later cross-references do not shift.

## 9. Core Experiment E3: Gemma Fine-Tuning Value

> **Result (2026-08-11).** Full table and reproduction commands in
> `data/reports/e3-sft-value-20260811/`. Three arms matched at 557 records and
> exactly 260,751 rendered tokens (relative gap 0.0), identical epochs/batch/
> accumulation so optimizer updates match, three seeds each, 150-instance
> cohorts, zero eval leakage on six dimensions.
>
> | cohort | Base | Mechanical | DirectEdit | **FuzzLang** |
> |---|---:|---:|---:|---:|
> | unseen file | 0.167 | 0.020 | 0.642 | **0.780** |
> | unseen project | 0.060 | 0.027 | 0.711 | **0.736** |
> | unseen project, excl. Abseil | 0.067 | 0.035 | 0.638 | **0.737** |
>
> Exact match on unseen files: 0.007 / 0.009 / 0.378 / **0.538**. Fine-tuning on
> FuzzLang data lifts verified repair from 16.7% to 78.0% on unseen files and
> from 6.0% to 73.6% on projects that contributed no training data, a transfer
> that also crosses C/C++. **Mechanical-SFT is worse than no fine-tuning**
> (0.020 vs 0.167), losing 25 of 26 decided pairs to the base model while having
> the lowest training loss of the three arms — the control that shows the gain
> is not simply more tokens, and a concrete reminder that loss is not quality.
>
> Caveat: Abseil is contaminated for the FuzzLang and Mechanical arms via
> `build/_deps/absl-src/` vendored into duckdb and protobuf; DirectEdit is
> clean.
>
> **The matched budget is a floor (E5, 2026-08-14).** 557 records is what
> DirectEdit could afford at one 31B call per record. Trained on 4,000 FuzzLang
> records — still cheap, and the pool holds 5,734 — the same arm reaches
> **0.893** on unseen files and **0.853** on unseen projects, both with
> intervals disjoint from DirectEdit's, and the curve is still rising. The
> unseen-project tie below is therefore an artifact of the shared budget. But
> the *matched* comparison also has to be corrected: on the de-vendored pool at
> 557 records FuzzLang scores **0.687** on unseen projects, not 0.736, and
> slightly below DirectEdit's clean 0.711 with overlapping intervals. **Do not
> quote 0.736.** See `data/reports/e5-scaling-20260814/`.
>
> **Correction (2026-08-13).** The `excl. Abseil` row was previously called the
> trustworthy unseen-project number. It is not. In this cohort **61 of 68
> diagnostics occur in exactly one project**, so the per-project and
> per-diagnostic breakdowns are the same table; diagnostic mix predicts every
> per-project rate to a mean absolute residual of 0.010. Dropping Abseil is
> justified as contamination control but simultaneously changes the diagnostic
> mix, so it is not the same comparison minus contamination. **Quote the
> full-cohort unseen-project figures (FuzzLang 0.736 vs DirectEdit 0.711, a
> tie), and do not read the per-project table as a project effect.** A real
> project effect needs a cohort stratified by diagnostic × project. See
> `data/reports/e3-project-confound-20260813/`.
>
> **Behaviour audit (2026-08-12, `data/reports/e3-quality-audit-20260812/`).**
> Compile-clean is satisfied by delete-to-compile, so every archived generation
> was re-read for edit-shape degeneracy. **93–96% of FuzzLang's verified fixes
> survive** — non-degenerate 0.729 (unseen file) and 0.709 (unseen project) vs
> DirectEdit 0.598 and 0.676, ranking unchanged and the unseen-project margin
> widened. Zero large deletions, zero empty repairs. Degeneracy tracks the
> **injector operation, not the generator** (`insert` 1.3–2.2% for both arms,
> `replace` 13–32% for both), because a `replace` overwrites the original
> statement and leaves the inverse task under-determined. The Mechanical
> control's collapse is explained: its reference repair is one character wide at
> every quartile, so it learned the identity map and **67.6% of its predictions
> are byte-identical to their input**.

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

**Status 2026-08-12 (`data/reports/e4-naterr-20260812/`).** The pipeline runs
end to end. `external/llvm-project` now carries full history (558k commits), so
the checkout prerequisite is met. Funnel: 2,039 reachable candidates → 682
self-contained single-file fixes → 163 reproduced typed diagnostics → **3
accepted paired records**, all isolated from the SFT arms.

Two things were settled by measurement:

- **Mining natural compile errors only works on very large, very fast
  projects.** Fix-build commits over full history: llvm 2,039 (since 2022-06),
  ffmpeg 81, abseil 3, json-c 2, leveldb 2. This is quotable in its own right —
  it is the motivation for a construction framework, measured on other people's
  repositories. It also means LLVM is the only source, and LLVM is the biggest
  training project, so `real/naterr_isolation.py` enforces file-level isolation
  rather than relying on project choice.
- **Natural compile errors are environment-bound, which caps this approach.**
  A snapshot campaign was built and priced (46 node-hours at ±3-day windows),
  then the premise was tested first. At the exact predecessor commit the
  candidate compiles cleanly — its fix was `+#include <atomic>`, a break only
  on a standard library without the transitive include. A ±3-day window gave 0
  reproductions from 5 candidates. The 163 "reproduced" were largely artifacts
  of compiling historical source against a mismatched header tree. The reason
  is structural: a large project's pre-merge CI covers the mainstream
  configuration, so the breaks that reach `main` and need a follow-up fix are
  the ones it misses — another compiler, standard library, platform, or build
  system. **Reproducing a natural build break costs a configuration matrix, not
  a git checkout.**

Together with the scarcity table, this is the measured case for constructing
errors rather than mining them, and both halves belong in the paper. The
campaign scripts stay checked in; running them is not recommended. A future
NatErr attempt should invert the premise: fix one configuration, then search
history for errors reproducible in it.

Lowering the pairing or no-test gates is still not an acceptable workaround.

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
- run the first zero-cost multi-project Injector replay measurement;
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
- ~~conduct minimality audits~~ — done 2026-08-12,
  `data/reports/e3-quality-audit-20260812/`; behaviour *preservation* beyond
  edit shape still needs the projects' own test suites, which this pipeline does
  not build.

### Week 6: Analysis and Artifact

- aggregate confidence intervals and coverage curves;
- produce per-family, per-project, and cost analyses;
- archive datasets, Injectors, adapters, logs, and manifests;
- write the paper around the frozen claims and completed evidence.

## 13. Critical Results Required for Submission

The paper is ready only when these four results exist:

1. a multi-project construction result: the released Injector library applied to
   correct, non-test source from several projects, with measured strict
   diagnostic coverage, multiplicity, per-Injector reach, provenance isolation,
   and the zero-GPU/zero-token replay cost;
2. a matched-budget Gemma SFT result demonstrating the value of FuzzLang data
   against equal-budget Mechanical and LLM-built data arms;
3. a generalization result: the same fine-tuned model repairs errors in a
   project that contributed nothing to training;
4. an external-validity result on a smaller, formal NatErr set.

Note what is *not* on this list: a head-to-head contest between the Injector and
a language model at generating errors. See the framing correction in §7.

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
- **Do not stage the FuzzLang Injector against a language model as a generator
  of errors.** FuzzLang is a near-zero-cost offline tool; an LLM given a
  concrete file and target will win that contest and the result says nothing
  about the dataset's value. A model-based generator is admissible only as an
  equal-budget training-data construction baseline inside E3.

These rules preserve a complete fallback paper: compiler-derived high-coverage
data, a narrow reusable Injector artifact, and a controlled Gemma SFT result,
even if advanced FuzzLang DSL features or large-scale NatErr reproduction do
not mature before the deadline.
