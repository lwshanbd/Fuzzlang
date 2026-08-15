# E1: Dataset construction at scale and near-zero cost

**What E1 establishes.** Point the released FuzzLang Injector library at
correct, non-test source from real projects and it produces compiler-verified
error/correct pairs across a wide range of diagnostics, using **zero GPU hours
and zero model tokens**. E1 measures how far that reaches — how many
diagnostics, how many distinct real translation units, how many projects,
including projects the library has never seen — and what it costs.

**What E1 is not.** E1 is not a contest between the Injector and a language
model at generating errors. See §1.

## 1. Retracted framing, and why

An earlier version of this document (and of `docs/plan.md` §7) defined E1 as
"FuzzLang Injector versus DirectEdit": both arms driven by the same local
Gemma-4-31B, one arm asking the model to edit each source file directly, the
other asking it to synthesize a reusable Injector. That experiment was built,
run, and is **withdrawn**. Two reasons, in order of importance:

**It did not test FuzzLang.** The "Injector" arm asked Gemma to *author* a
FuzzLang DSL Injector on the spot from TableGen and emission evidence. The
actual FuzzLang Injector library is *distilled* from already-verified pairs
(1,413 recipes extracted from 1,422 verified records; 594 → 1,239 portable
after the v1 expansion). The run therefore compared two ways of prompting
Gemma. It never exercised the tool whose value the paper claims.

**The question was malformed.** FuzzLang is a near-zero-cost offline tool. A 31B
model handed a specific translation unit and a specific target diagnostic will
naturally beat a deliberately narrow single-site lexical rewriter at
first-attempt success. Winning that contest was never the claim, and losing it
is not evidence against the dataset. Reporting it as a headline invites exactly
the misreading it received: a reader concluded "the LLM generates errors much
better than the Injector", which is both true and irrelevant.

### 1.1 The withdrawn numbers, recorded once

Kept so the result is not re-derived, and so anyone who encounters it knows its
status. 21 diagnostics, 6 real source TUs each, one Tioga node, Gemma-4-31B,
`candidates=4`, `temperature=0.5`, seed 20260807. Run directory
`data/gen/experiments/e1-injector-vs-directedit-v0001/run-smoke/`.

| | DirectEdit (Gemma per file) | Gemma-synthesized Injector |
|---|---:|---:|
| diagnostics with ≥1 record | 14 / 21 | 2 / 21 |
| accepted records | 43 | 5 |
| macro exact-target rate | 0.341 | 0.040 |
| cross-project (Abseil) transfer | 0.310 | 0.000 |
| model calls / output tokens | 126 / 30,212 | 21 / 22,908 |

All 48 accepted records pass the full invariant audit (no test sources, every
`corrected_src` present, every primary diagnostic exactly the requested target,
no opportunistic relabelling). The measurement is sound; the *question* is not.
**This table must not be cited as evidence about FuzzLang.** It says only that
one prompting strategy for Gemma beat another prompting strategy for Gemma.

Two by-products of that run are worth keeping:

- **A real defect was found and fixed.** Gemma frequently emits `"target": {}`,
  and the request-bound envelope restoration that the append-fragment path
  already had was never wired into the lexical direct-synthesis path, so every
  candidate was rejected as `schema_validation: 'diag_name'`.
  `_restore_request_bound_envelope` is now shared by both paths; offline
  revalidation of the archived responses moved 0/84 → 64/84 accepted. The
  pre-fix run is retained as `run-smoke-prefix-envelope-bug/`.
- **The harness is reusable.** Budget accounting (model calls, output tokens,
  model seconds, wall seconds, compiler invocations), the strict acceptance
  gate, per-attempt archival, and the bootstrap/paired statistics in
  `e1_report.py` are generator-agnostic and carry over to the corrected E1 and
  to E3's data-arm construction.

## 2. Protocol, as implemented

`gen/fuzzlang_dsl/library_replay.py` is the engine and takes **no backend
parameter**: zero model calls is a structural property, not a discipline.
`run_e1_library_replay.py` is the CLI, `run_e1_library_replay_arms.sh` runs
every arm on one node, and `run_e1_construction_report.py` builds the table.

**Library.** The pinned artifact is assembled from the 622 Injector files the
canonical audit checksums: **9,760 portable Injectors over 1,615 target
diagnostics** (9,471 C++ / 289 C). It matches the canonical audit exactly.

**Operation families, reported separately.** 8,235 Injectors are *lexical*
(`replace`/`insert`/`delete`) and must match a token pattern in the target file
— this is the genuine cross-source transfer claim. The remaining 1,525 are
*append* fragments, which match any file trivially. Mixing them would let the
append family consume the verification budget and inflate the transfer number,
so each family is run and reported on its own.

**Sources.** 13 projects, clean-gated with the pinned patched Clang at
`llvmorg-22.1.8`, production-only, no test or test-support paths.

**Splits, frozen before generation** (`run_freeze_source_splits.py`, seed
20260808, 15%):

| split | projects | TUs |
|---|---:|---:|
| `train` | 9 (LLVM, protobuf, duckdb, curl, libuv, yaml-cpp, zlib, spdlog, fmt) | 2,694 |
| `eval_unseen_tu` | the same 9 | 440 |
| `heldout_project` | 4 (Abseil, FFmpeg, leveldb, json-c) | 2,263 |

Assignment is a fixed hash threshold on `(seed, source_id)`, not a rank over the
pool, so adding projects later cannot flip a source that has already been used.
Emitting a training record from a held-out source raises rather than relabels.

**Acceptance** is the project-wide rule: clean parent, failing mutant, primary
typed diagnostic exactly equal to the Injector's declared target (name and
DiagID), `corrected_src` retained, no test or test-support source, no
opportunistic relabelling to whatever error happened to fire.

**Caps.** At most 3 records per source TU, 5 per diagnostic, and 24 compiler
verifications per source. The verification cap matters because a compile costs
about three orders of magnitude more than a lexical match; each translation unit
is tokenized once and the index is shared across the whole library.

## 3. Reported quantities

**Reach.**

- strict diagnostic coverage and multiplicity, per project and unioned, against
  the frozen 1,935-diagnostic denominator;
- structurally unique records; distinct source TUs and projects reached;
- sources and projects reached per Injector — the amortization curve;
- yield on translation units, and separately on **projects the library never
  saw**, which is the transfer claim.

**Cost.**

- GPU hours and model tokens for replay: **zero, by construction**;
- compiler invocations per accepted record and wall-clock per 1,000 records;
- the one-off cost already sunk in building the library, reported separately so
  replay cost and construction cost are never conflated.

**Limits.** Failure categories are reported, not hidden: Injector does not match
the source, clean mutant, wrong diagnostic, timeout, oversized edit, parent
does not compile.

## 3.1 Result (2026-08-08, recounted 2026-08-12)

Full table, per-project breakdown, and reproduction commands:
`data/reports/e1-construction-20260812-devendored/`. Every arm made **zero
model calls**.

The counts below exclude fetched-dependency source. The 08-08 release
attributed it to the project that fetched it — duckdb and protobuf vendor
Abseil and others under `build/_deps/` — and `is_vendored_path()` now rejects
those trees. The recount drops 2,090 of 15,097 records, confined to three
projects (duckdb 1,941 → 167, protobuf 1,199 → 891, yaml-cpp 91 → 83). Both
`heldout_project` arms are unaffected: none of the four held-out projects
vendors anything.

| ops | split | sources | records | diagnostics | projects | vendored dropped | wall (s) |
|---|---|---:|---:|---:|---:|---:|---:|
| lexical | train | 2,694 | **4,633** | **382** | 9 | 1,131 | 5,104 |
| lexical | eval_unseen_tu | 440 | 1,088 | 107 | 9 | 192 | 613 |
| lexical | heldout_project | 2,263 | **2,325** | **138** | 4 | 0 | 139 |
| append | train | 2,694 | 1,109 | 66 | 9 | 597 | 6,509 |
| append | eval_unseen_tu | 440 | 623 | 33 | 9 | 170 | 1,214 |
| append | heldout_project | 2,263 | 3,229 | 131 | 4 | 0 | 150 |

Union: **13,007 records, 514 diagnostics (459 in the 1,935 paper scope), 3,714
source TUs, 13 projects, 395 diagnostics at multiplicity ≥ 3.** Plan targets for
record count (10,000–30,000), project count (≥ 3), and multiplicity-three
(350–400) are all still met; RealSource strict coverage (459/1,935) is below the
~1,000 goal, as one capped pass should be.

**Amortization.** In the lexical train arm, 395 Injectors produced a record,
averaging 11.7 distinct source TUs each, and **110 crossed a project boundary**.
Pooled over all arms: 610 Injectors, 21.3 sources each. These are lower than the
08-08 figures (419 / 13.8 / 150 and 632 / 23.9) precisely because an Injector
that "reached duckdb and protobuf" through each project's copy of Abseil was
reaching one codebase twice.

**Transfer.** On the four projects the library has never seen, lexical Injectors
produced 2,325 records over 138 diagnostics from 987 TUs in **139 seconds on one
node with no model call** — unchanged by the filter.

**Integrity.** All 15,097 generated records pass the invariant audit with zero
violations; 13,007 of them additionally come from source that is genuinely the
project it is attributed to.

**Configuration finding.** The first run retained 484 records over 120
diagnostics while actually verifying 7,761 and discarding 7,277: each of 32
shards spent the full per-diagnostic cap independently, and the surplus was
trimmed after the merge. Replacing that with a shared locked budget claimed
before compiling, plus round-robin ordering of the library by target diagnostic,
gave 5,764 records and 401 diagnostics from the same inputs on the same node.
The pre-fix arm is kept as `lexical-train-cap5-fileorder/`.

## 4. The claim, stated as a cost/reach sentence

> Applying the released FuzzLang Injector library to a previously unseen project
> produces N compiler-verified paired records covering K distinct diagnostics,
> using zero GPU hours and zero model tokens.

Existing zero-API evidence already has this shape and needs only to be turned
into a released multi-project measurement:

- 896 structurally retained records on 428 unseen LLVM translation units, no
  model or API call;
- 97/97 and 100/100 exact-target records from 64 and 51 sources on held-out
  Abseil at commit `1e6d60b2ca9356542fe62b73ab010424aa2796cf`, no model or API
  call, with 46 target diagnostics outside the original portable space.

Where a per-record model generator is measured at all, it is measured only to
**price the alternative** — GPU hours and tokens for an equal number of
accepted records — never to declare a winner at error generation.

## 5. Relationship to the other experiments

E1 shows the dataset is broad and nearly free to produce. It does not by itself
show the dataset is *useful*; that is E3, where a model-built data arm finally
has a meaningful role — as an equal-budget training-data baseline, answering
"does FuzzLang-built data train a better repair model than LLM-built data of the
same size and token budget?" That is a question about data value, and it is
worth answering. "Which one writes better errors" is not.
