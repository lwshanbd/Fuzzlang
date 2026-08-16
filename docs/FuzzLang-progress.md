# FuzzLang: Progress

Status against `FuzzLang-Proposal.md` and the executable plan in `plan.md`.
LLVM is pinned to `llvmorg-22.1.8`; the test suite has 748 passing and 5
environment-dependent skips. Detailed generation history is in
`data/gen/README.md`.

## Where things stand (2026-08-14)

Read this section first. Everything below it is detail and history.

**The paper needed four results. Three are done.**

**1. Coverage — done.** FuzzLang produces compiler-verified errors for **1,208
of the 1,935** diagnostics in scope (62%). Every input is checksummed and the
number regenerates from one command. Four different coverage figures circulate
in older notes; `data/reports/strict-coverage-20260812-release-union/coverage_numbers.csv`
says which to use where. Quote 1,208. Do not quote 1,538.

**2. Building the dataset — done.** Replaying the injector library over 13 real
projects produced **13,007 verified records covering 514 diagnostics**, using
**no GPU time and no model calls**. One injector reaches about 12 source files
on average, and 110 of them work across project boundaries. On four projects
the library had never seen, it produced 2,325 records in 139 seconds.

**3. The dataset makes a model better — done, but state it against the right
baseline.** Fine-tuning Gemma-3-4B on 4,000 FuzzLang records reaches **89% on
unseen files and 85% on unseen projects**, and the curve has not flattened. A
control trained on mechanical mutations comes out *worse* than no fine-tuning at
all, because its repairs are one character wide and the model just learns to
copy its input.

**Do not quote "17% → 89%".** The 4B base model's 17% is a weak comparison. An
un-fine-tuned **Gemma-4-31B scores 74% and 79%** on the same cohorts, so most of
that gap is base-model choice, not what the data teaches. The claim the evidence
supports is:

> A 4B model fine-tuned on 4,000 FuzzLang records beats a model eight times its
> size that has not been fine-tuned: **+0.153** on unseen files [+0.087, +0.220]
> and **+0.067** on unseen projects [+0.000, +0.133], instance-paired.

The 31B is not cheating — a degeneracy audit finds delete-to-compile behaviour
in 1.8% of its fixes, lower than the fine-tuned model's 6.6%. It produces
genuine alternative repairs; it just rarely picks the developer's, reproducing
the reference on 3% of instances against the fine-tuned model's 73%. Report that
as *agreement with the reference repair*, and note the confound: the fine-tuned
model was trained on records from the same injector library that built the
evaluation. See `data/reports/e7-model-scale-20260815/`.

**4. Errors we did not create (NatErr) — not a dataset, but a finding.** We
tried to mine real compile errors from git history and got 3 usable records.
Two measurements explain why, and both are worth publishing:

- Natural compile errors are **rare**. Across full project histories: LLVM
  2,039 candidates, FFmpeg 81, Abseil 3, json-c 2, leveldb 2.
- They are **tied to a build configuration**. Rebuild LLVM at the exact commit
  and the error usually does not appear, because most "fix build" commits repair
  a break in some *other* compiler, standard library, or platform.

Together these say the supply of reproducible natural errors is small and does
not grow with effort. That is the argument for constructing errors instead.

**The dataset is packaged (2026-08-14).** `FuzzLang-RealSource v1` is frozen at
`data/gen/releases/fuzzlang-realsource-v1/`: 13,007 records over 514
diagnostics, split train 5,742 / eval_unseen_tu 1,711 / heldout_project 5,554,
with a manifest, per-file checksums, and a 51 MB bundle. All eight release gates
pass on every record; a single failure aborts the freeze. Two imbalances are
documented rather than smoothed over: LLVM is 65% of `train`, FFmpeg is 87% of
`heldout_project`, and the language mix flips from 75% C++ in training to 88% C
in the held-out split.

**More data or more variety? Answered (2026-08-15) — it is the data.** Two arms
of 3,500 records each, one covering 135 diagnostics and one covering 427:
0.873 vs 0.900 on unseen files, 0.800 vs 0.833 on unseen projects. Both paired
intervals include zero, and the arms agree on 136 of 150 instances. Tripling
diagnostic coverage at a fixed record count buys little.

The reason is a better result than the one we were looking for. The narrow arm's
training touched the diagnostic of only 42 of 150 unseen-project instances. It
scored **0.810 on those and 0.796 on the 108 diagnostic types it had never seen
once.** The model is not learning per-error fixes; it is learning to read a
diagnostic and repair code, and that transfers to error kinds absent from
training.

So state breadth where it belongs: it is what makes the **dataset** a
coverage-driven benchmark that can expose gaps, not what makes a fine-tuned
model better. See `data/reports/e6-breadth-20260815/`.

**What is still missing.**

1. **Only the 4B has been fine-tuned.** The 31B has been measured zero-shot but
   never trained, so we cannot say whether FuzzLang data helps a model that is
   already competent, or only one that is not.
2. **The 31B was evaluated at a 512-token output budget** chosen when every
   model under test was fine-tuned to be terse. It is verbose, and 11 of its 12
   parse failures are truncations. A re-run at 1,024 is outstanding; it raises
   its numbers somewhat and cannot flip the unseen-file result.

**Corrections made recently — do not cite the old numbers.**

- FuzzLang on unseen projects at the matched 557-record budget is **0.687**,
  not the 0.736 in the original E3 report. The old figure came from a pool that
  included vendored Abseil source.
- The per-project results table does **not** measure a project effect. In that
  cohort 61 of 68 diagnostics appear in only one project, so the table is
  really reporting which diagnostics each project happened to get.
- E1's per-project counts were recomputed after excluding vendored
  dependencies: duckdb fell from 1,941 records to 167, protobuf from 1,199 to
  891.

## Submission Readiness and Generation Freeze (2026-08-07, superseded)

> Superseded by the section above. Two items it lists as missing — the
> multi-project Injector replay and the multi-seed SFT evaluation with an
> unseen-project column — are now complete. The canonical-audit guidance below
> is still correct for the batch-6 lineage in isolation, but the released
> headline is the union audit, not this one.

**The project is not submission-ready yet.** The implementation, paired-data
pipeline, and small matched-token SFT result are strong feasibility evidence,
but the paper still needs a canonical dataset release, a multi-project
zero-cost Injector replay measurement, multi-seed SFT evaluation with an
unseen-project generalization column, and formal NatErr external validity.

For the active `+300 diagnostic types relative to batch 6` objective, the
authority is now the **canonical union audit** in
`data/reports/strict-injector-coverage-20260807-canonical/` (see its README for
the full derivation and the input delta against the audits it replaces). It
supersedes `strict-injector-coverage-audit-batch0053-direct-fixed.json`
(1,200 / 1,935, +171) and the later live `build_batch0074_final_audit.py` output
(1,241 / 1,935, +212), both of which enumerated different subsets of the same
completed campaigns. Regenerate it with:

```
PYTHONPATH=src python3 src/gen/fuzzlang_dsl/run_canonical_strict_audit.py \
  --audit-out data/gen/experiments/clang-test-gap-injector-v0002/canonical-strict-injector-audit-20260807.json \
  --report-dir data/reports/strict-injector-coverage-20260807-canonical
```

| rule | paper-scope types | batch-6 baseline | new vs batch 6 | strict records |
|---|---:|---:|---:|---:|
| **strict target-only (headline)** | **1,195 / 1,935** | 981 | **+214** | 6,850 |
| inclusive (the earlier audits' rule) | 1,242 / 1,935 | 1,029 | +213 | 7,535 |

The two rules read identical inputs and differ only in whether a record whose
`target_diag` was relabelled to the diagnostic the mutation happened to emit
counts. 685 admitted records are such opportunistic relabellings, and 47
paper-scope types rest on them alone; the strict rule drops them because they
are not evidence that the *requested* gap was reached. Both baselines are
recomputed from the batch-6 inputs under the same rule, so a strict numerator is
never compared against an inclusive baseline.

The objective therefore remains **115 types short** of the 1,329-type goal on
the inclusive rule and **134 short** on the strict rule. Candidates, running
synthesis, and incomplete replay outputs are not coverage. All generation jobs
are stopped, so these inputs are final.

**Superseded by the release union (2026-08-12).** The table above covers the
batch-6 campaign lineage only. Folding the multi-project library replay (E1)
into the same audit by one command — `run_canonical_strict_audit.py
--extra-input LABEL:INJECTOR:RECORD`, six arms, all 15,097 records admitted with
**zero rejections** — gives the number the paper should quote:

| rule | paper-scope types | new vs batch 6 | records | relabel-only types |
|---|---:|---:|---:|---:|
| **strict (headline)** | **1,208 / 1,935 (62.4%)** | **+227** | 21,947 | **34** |
| inclusive | 1,242 / 1,935 | +213 | 22,632 | — |

The strict count rose by 13 while the inclusive count did not move at all: those
13 types had been reachable *only* through opportunistic relabelling, and
replaying the library over real project source reached them **on target**.
Paper-scope types resting on relabelling alone therefore fall from **47 to 34**.
Applying the library to source it has never seen both extends and hardens
coverage. See `data/reports/strict-coverage-20260812-release-union/`.

The report also preserves an older historical FuzzLang-Breadth composite of
1,538 / 1,935. That value and the active-goal audit use different input unions,
so they must not be added, substituted, or used interchangeably in a paper
table. **1,538 is not the paper's coverage claim; 1,208 is.**

**Execution decision.** Do not launch further exploratory breadth campaigns.
Let already-submitted target-only synthesis/replay chains complete; then run a
canonical union audit. If it reaches 1,329 types, freeze the Injector library
and dataset. If it does not, generate only the exact remaining gaps. Shift
subsequent compute to E1 (multi-project zero-cost Injector replay), E3
(multi-seed matched-budget SFT plus unseen-project generalization), and E4
(NatErr).

## Live Strict Injector Campaign (updated 2026-08-07)

### Completed Fixed-Input Increment (2026-08-07)

The completed test-evidenced preprocessor campaign is now included in a newer
fixed-input audit.  Relative to batch 6, the frozen union of the completed
ordinary-C++23, emission, recovery, and preprocessor inputs adds **109**
paper-scope diagnostics: **1,138 / 1,935**.  The preprocessor route supplies
the additional **28** exact replay-verified types; its 70 local-Gemma requests
all start from clean, non-test LLVM source files, and every admitted pair
retains `corrected_src`.  The auditable artifact is
`data/gen/experiments/clang-test-gap-injector-v0002/strict-injector-coverage-audit-batch0036-fixed.json`.

This is still a fixed completed subset.  The running C++ emission-tail, C11,
C++20, and direct-DSL queues are deliberately excluded until their own output
and replay inputs are frozen.

**Interim fixed-union update (2026-08-07).** The completed C11 B49 replay has
now been merged with that fixed subset (the C++ emission-tail remains running
and is still excluded).  The resulting strict paper-scope union is **1,153 /
1,935**, or **+124** diagnostic types relative to batch 6.  This is an
interim checkpoint, not a replacement for the final all-wave audit: every
count still requires a clean non-test parent, `corrected_src`, a portable
Injector, and an exact typed replay.

**Current fixed-input update (2026-08-07).** The later B53 fixed audit adds
completed emission-tail and direct-Injector replays to that historical B49
checkpoint, yielding **1,200 / 1,935** strict C/C++ types and **+171** types
relative to batch 6. This is the authoritative numerator for the active +300
goal. Its fixed inputs are recorded in
`strict-injector-coverage-audit-batch0053-direct-fixed.json`; it is still not
the final canonical release-union audit described above.

**Strict target-only replacement (submitted 2026-08-07).** The first
emission-tail and Abseil-tail launchers were stopped before replay after an
integrity check found that their explicit `ADMIT_OBSERVED_ERRORS=1` setting
could relabel an easier, already-covered observed diagnostic as the target of a
request for a harder gap.  Their checkpoints are retained for forensic
comparison but are excluded from every coverage numerator.  The replacement
single-node lane B62 processes **265** LLVM C++23 TableGen/emission targets;
264 remain gaps under the current fixed union because one was covered by the
subsequently completed C11 batch.
The runner now defaults to target-only admission: a model candidate must emit
the requested typed diagnostic and its distilled portable Injector must replay
to that same name and DiagID.  A pre-replay gate rejects any opportunistic
outcome or Injector target outside its original request list.  Regression-test
text remains prompt-only evidence, while every retained parent is clean,
non-test real LLVM or Abseil code.  These runs use at most two nodes and remain
outside the numerator until their independent replay and fixed audit complete.

**Test-mode compatibility correction (2026-08-07).** A first B63 checkpoint
showed that a diagnostic can be test-reachable only under a non-transferable
configuration (for example, `-cc1`, a target triple, MS extensions, or a test
macro), despite passing a name-based ordinary-C++ filter.  B63 was therefore
withdrawn before replay.  Its replacement B64 derives its target list from the
pinned test-scan `trigger_configs`: it retains only scans using `-x c++` and a
C++2b/C++23/C++2c standard, without a target, `-D`, or additional `-f` mode.
This produces 95 source-bindable current gaps (190 independent Abseil real
source requests).  The initial B64 code-witness attempt was stopped after 144
strictly rejected candidates and **zero** Injector/record admissions: a trigger
configuration by itself did not expose enough semantic structure for this
long-tail set.  It is excluded from coverage and retained as a negative result,
not silently relabelled as a success.

**Disjoint C++20 tail (active 2026-08-07).** B66 contains 200 further
C++20-compatible, compiler-emission-evidenced targets (400 clean LLVM source
requests).  Its selector excludes all B62/B64 target names, so its eventual
strict replay has 200 distinct-type capacity.  B62 and B66 are the only active
generation lanes; both use target-only admission and remain outside the
numerator until replay and a frozen union audit complete.

**Live target-only checkpoint (2026-08-07).** B62 has currently produced
**63 candidate target diagnostic types** whose first compiler outcome matches
the requested name.  Its replay has not started, so it contributes **zero**
strictly verified types at this checkpoint.  B66 has processed 67 target types
with zero target matches so far and likewise contributes zero verified types.
Therefore the new B62/B66 goal wave has added **0** error types to the strict
numerator to date; its candidates are not added to the later fixed **1,200 /
1,935** (**+171**) active-goal checkpoint. Candidate matches are intentionally not
reported as coverage until a portable Injector reproduces the same typed
diagnostic on a clean, non-test paired source.

**Direct FuzzLang-Injector recovery (queued 2026-08-07).** B68 retries the
95 B64 gaps by asking Gemma-4-31B to author lexical FuzzLang DSL Injectors
directly from TableGen/emission evidence, two clean Abseil source windows, and
the typed test-trigger configuration.  B69 is a separate schema-v2 append
fragment route for the same targets: 84 prompts additionally contain a compact
Clang regression-test excerpt, while the remaining 11 retain only their typed
configuration.  Test excerpts are prompt evidence only; they never become a
dataset source.  Both waves are serialized after B66/B68 respectively, so
there are no more than two nodes in use, and every candidate must pass clean
parent compilation and exact typed replay on non-test Abseil code before it
can affect coverage.

**Residual test-first and compiler-evidence waves (queued 2026-08-07).** B70
extends the test-first set with the 13 still-unselected C++ module diagnostics
and two C23 diagnostics for which the pinned scan has an ordinary-language
trigger.  It replays only on clean LLVM and FFmpeg sources.  Once those
test-evidenced routes have completed, B72 and B73 apply the same direct
append-Injector protocol to the 200 C++20 and 265 C++23 TableGen/emission-tail
targets respectively.  These waves explicitly disable the *test-evidence
selection* filter because they are the documented compiler-emission fallback;
they do not weaken the clean-parent, non-test provenance, portable-Injector,
or exact typed replay gates.  B75 additionally retries the 68 B66 targets
whose pinned Clang scan confirms a trigger, now carrying that typed trigger
configuration through direct append-Injector synthesis.  All are pending work,
never coverage claims.

After that audit, a separate cross-project Abseil C++23 wave is staged on two
serialized one-node lanes.  Its 300 real-source target candidates are rebuilt
and filtered at run time against the prior frozen audit; the current audit
would retain 250 prompt-test-evidenced targets with 1,000 clean Abseil witness
windows.  This is deliberately a pending target capacity, not a coverage
numerator; each proposed Injector still needs an exact typed replay on a
non-test source before it can count.

If that direct-DSL audit remains below the active +300-type objective, a
single-node conditional hybrid fallback runs on the same remaining Abseil
test-evidenced targets. Gemma first constructs a mutation on a clean real
source witness; FuzzLang then distills and replays the resulting portable
Injector. The fallback exits before generation when the preceding strict audit
already reaches the goal, and is separately labelled so direct and hybrid
provenance are never conflated.

A second conditional fallback is staged only after that hybrid audit: it binds
the then-uncovered ordinary C++17 test-evidenced gaps to a 1,999-TU clean LLVM
source pool that is disjoint from earlier recorded LLVM parents. It too exits
without model work once the +300-type result is already proven.

The final staged conditional route is language-complementary: it uses clean
FFmpeg C99 production translation units for the remaining ordinary C
test-evidenced gaps (98 under the current fixed audit). It follows the same
paired-source, typed-diagnostic, non-test replay gates and exits without GPU
work when a preceding audit has already proven +300.

The ordinary, paper-scope Clang-test-reachable gap has only 246 types under
the current fixed audit.  Therefore a final conditional C++20 TableGen-tail
route follows the C99 audit if the +300 objective is still unproven.  It
selects up to 300 additional *ordinary* C++20 diagnostics after applying the
same `data/gen/out_of_scope.txt` exclusion list, binds each to four clean
production LLVM source windows, and gives Gemma compiler emission-site
evidence rather than a regression-test source.  Its 1,200 requests, Injector
replay, and fixed audit are all dependency-gated; it consumes no GPU time once
an earlier strict audit has reached +300.  This keeps Clang tests as the first
target-prioritization signal while making the stated coverage objective
feasible without ever making test code a dataset source.

If that C++20 tail remains below the objective, the next dependency-gated
route repeats the same compiler-evidence and exclusion gates over clean FFmpeg
C99 production TUs. It is intentionally language-complementary rather than a
second run over the same C++ source distribution, and likewise exits before
Gemma generation if the preceding fixed audit already proves +300.

One final conditional route then applies the same TableGen-tail procedure to
clean Abseil C++23 production TUs. This adds an external C++ source
distribution and C++23 semantic surface after the LLVM C++20 and FFmpeg C99
tails, while retaining the identical non-test, portable-Injector, exact typed
replay, and fixed-audit gates.

### Earlier Completed Fixed-Input Increment (2026-08-07)

The completed ordinary-C++23 breadth and emission campaigns have a separate,
stable audit that deliberately reads only the frozen batch-6 inputs plus those
two completed campaigns.  It does **not** read any concurrently written queue
output.  The audit adds **81** exact replay-verified diagnostics in the paper
scope, moving the fixed-input result from **1,029 / 1,935** to
**1,110 / 1,935**.  It contains 66 breadth types and 15 emission-context
types; every included record retains `corrected_src` and passed the non-test
source-path gate.  The machine-readable artifact is
`data/gen/experiments/clang-test-gap-injector-v0002/strict-injector-coverage-audit-batch0034-fixed.json`.

This is a bounded completed increment, not a replacement for the later full
batch audit: the high-depth, cross-project, C11, and direct-DSL campaigns
remain intentionally excluded until each has completed replay.

The required lower bound of **250 distinct Clang TableGen error diagnostics**
has been surpassed. The paper headline uses the frozen **strict C/C++ code
scope**: **1,935** source-level diagnostics after excluding 402
invocation/environment diagnostics and 1,554 non-standard-dialect or
hardware-target code diagnostics. The latest full-release strict Injector audit covers
**1,029 / 1,935 (53.2%)** of that paper scope. It is backed by 6,920 paired
records and 9,342 unique portable Injectors, counts a compiler-verified first
application of a portable Injector to its real source witness, reports
cross-source replay separately (695 types), rejects records that lack the
concrete Injector required by their replay provenance, and excludes
test/test-support sources.

For transparent operational breadth tracking, the same audit also reports the
unfiltered TableGen result: **1,178 / 3,891** catalog error types. The 149
accepted types classified outside the paper scope remain archived and auditable
but never contribute to the paper numerator or percentage.

The machine-readable snapshot is in
`data/reports/strict-injector-coverage-20260805-batch0006/`: its Injector inventory
maps all **9,342** portable Injector IDs to their target diagnostic (1,415
distinct target names), while the strict paired-record audit establishes that
**1,178** of those target names are actually covered. Its TableGen gap CSV
lists all **2,713** uncovered error diagnostics with component, message,
Clang-test reachability, and non-test emission-context availability.  The
distinction is intentional: an Injector artifact alone is not coverage until
compiler replay produces an exact-target paired record.

`paper_scope_summary.csv` in that snapshot freezes the mutually exclusive
denominator arithmetic and the current **1,029 / 1,935** paper-scope result.
`data/gen/out_of_scope.txt` is the audited name-level exclusion list used to
derive it; the full-catalog CSVs are retained as a secondary operational view.

The snapshot now also contains a diagnostic-level index: it aggregates the
number, language, and operation of portable Injectors per target type, while
retaining the one-row-per-Injector inventory for exact lookup.  These CSVs
are metadata only: neither carries a test source, an Injector payload, or a
training example.

### Recorded Injector and Gap Inventory

The checked-in snapshot above is also the current machine-readable inventory.
It separates an Injector's *declared target* from a diagnostic type that has
actually passed the strict paired-record replay gate:

| question | file | current answer |
| --- | --- | --- |
| Which Injector targets which diagnostic? | `injector_diagnostic_inventory.csv` | 9,342 portable Injector IDs map to 1,415 target diagnostic names. The `strict_diagnostic_covered` column identifies the 1,178 target names with at least one exact-target paired record. |
| How many Injectors target each diagnostic? | `diagnostic_injector_summary.csv` | One row per target name; includes Injector count, language, operation, and strict-coverage status. |
| Which catalog errors remain uncovered? | `uncovered_tablegen_errors.csv` | 2,713 TableGen error types, each with component, message template, Clang-test reachability, and non-test emission-context availability. |
| What are the paper headline totals? | `paper_scope_summary.csv` | The frozen 1,935-type strict C/C++ code denominator and the current 1,029-type Injector coverage. |
| What are the full-catalog totals? | `summary.csv` | The 3,891-type operational denominator and all coverage, Injector, and test-reachability totals. |

Thus the inventory does **not** claim that all 1,415 Injector target
names are covered: 237 target names currently have a portable Injector but no
strictly accepted paired replay.  They remain generation work, as do the
2,713 catalog names in the gap file.

### Pending Direct-Injector Ledger (updated 2026-08-05)

`staged_direct_injector_targets_20260805.csv` records the current staged
local-Gemma work separately from the verified inventory.  It contains **198**
distinct, currently uncovered TableGen error types, represented by **236**
direct Injector requests and **696** independently clean-gated non-test source
witness requests.  Each row includes the target name, component, language
mode, contributing batches, and whether the target is test-reachable.  All
198 are current strict catalog gaps and all are marked
`strict_diagnostic_covered=false`.

This ledger is deliberately not an Injector count: it is the input to Gemma,
which must first emit a portable FuzzLang Injector.  Only a subsequent replay
that has a clean parent, a paired `corrected_src`, no test/test-support
provenance, and an exact matching primary typed diagnostic can add the
resulting Injector and record to a future strict snapshot.  The ledger covers
the newly prepared Objective-C/Objective-C++, C11 `defer`, GNU/MS inline-asm,
i386-Darwin target, 40-type OpenMP, 11-type OpenACC, 40-type ordinary
C++23 preprocessor/pragma, three ordinary inline-asm, one RISC-V RVV, and two
Blocks-enabled routes, along with earlier pending direct routes.

**Batch 6 (completed, 2026-08-05).** The repaired C++98 local-Gemma rerun
produced one portable Injector and one clean, non-test paired replay for
`err_empty_scalar_initializer`. It passes the exact-primary-diagnostic and
Injector-provenance gates, so the strictly verified total increases by one
type and one record. The auditable machine-readable release is
`data/gen/experiments/clang-test-gap-injector-v0002/strict-injector-coverage-audit-batch0006.json`;
the checked-in CSV snapshot above was regenerated from that audit.

Batch 5 incorporates three completed local-Gemma campaigns: the C23 standard
route, an OpenMP route, and a C++23 retry route. The final combined strict
audit admits 11 new exact target types and records after deduplication and
Injector-provenance checks. The full release decision is recorded in
`data/gen/experiments/clang-test-gap-injector-v0002/strict-injector-coverage-audit-batch0005.json`.

Batch 4 incorporates the completed second MS-extension run and first OpenACC
run. Their 18 accepted paired records add 18 exact target types. The full
release decision is recorded in
`data/gen/experiments/clang-test-gap-injector-v0002/strict-injector-coverage-audit-batch0004.json`;
the snapshot README documents the CSV columns and admission criteria.

This audit update includes the completed C++11 and two ordinary-C++23
test-gap batches: their 40 new records passed the paired-source,
non-test-source, and exact-target gates. Two independently verified
cross-target replays contribute two more new types. The next two C++23
campaigns are prepared but deliberately excluded from this completed snapshot.

The subsequent 62-target ordinary-C++23 campaign completed with **zero**
accepted Injectors and **zero** records, so it does not change the snapshot or
the CSVs. Its parent-source pool was stale for most requests, and the remaining
candidates failed the exact-primary-diagnostic gate. A replacement campaign is
queued behind a refreshed pool of 400 clean, non-test LLVM C++23 translation
units; it will be audited and appended only after the same release gates pass.

The first launch of the replacement's C++23 tail and the independent C++98
tail reached local-Gemma health but exited in the GPU-service wrapper before
the Injector runner began. They produced no candidates, Injectors, or records
and are therefore excluded from the batch-5 snapshot. The wrapper has been
fixed: the C++98 strict retry subsequently produced the batch-6 accepted
`err_empty_scalar_initializer` replay above. The C++23 retry and remaining
clean-source recovery queue still require their own completed strict audits.

**Additional clean-source recovery queue (2026-08-04).** To recover target
types that were previously missed because an old parent source was stale or a
single source witness did not give the model enough usable context, four
dependent local-Gemma runs are now staged after the existing retries.  They
contain 468 requests over **154 distinct current strict gaps**: 62 ordinary
C++23 types from the stale-parent batch, 8 remaining C++17 types, and two
otherwise-unqueued C++23 groups of 36 and 50 types.  Each target is bound to
three independently clean-gated, non-test real source witnesses.  The C++17
and C++23 groups share two target names, hence 156 target selections reduce to
154 distinct names.
Clang-test evidence is prompt-only, and this queue remains excluded from the
strict snapshot until every accepted Injector has itself replayed to the exact
target diagnostic.

The current expansion queue is broader than that replacement alone. At this
report cut, **32** request batches await a Gemma output; together they bind
**990** real-source requests to **542** distinct Clang-test-reachable strict
gaps across ordinary
C++23, C++20 coroutines, C++11/C++2c/C23/C11/C++98, MS
extensions/compatibility, OpenMP, OpenACC, Blocks, a separately constrained
preprocessor route, modules, and ordinary C99. Every one has a clean,
non-test source witness; source variants deliberately give the same target
more than one chance to transfer. The new C++20 coroutine route contributes
five test-reachable diagnostic types with three independent LLVM source
witnesses each; the OpenMP tail contributes two more with the same
three-source replication; the ordinary C++23 source-extension route adds five
compiler-prechecked nullability/address-space types; and the C++98 tail adds
19 standard-only types from the one available clean LLVM C++98 production TU;
and the TableGen-Summary route enables three further C++23 types that the
former catalog parser had treated as message-less. A final source-level
attribute route adds `err_attribute_pointers_only` on three independent LLVM
C++23 witnesses; a source-prechecked availability route adds four types on
three witnesses each; and the final ordinary C++23 route targets the
source-verified variadic calling-convention error. The modules route retained
7 / 400 clean-gated LLVM C++23 production TUs under `-fmodules` and bound 37
module-target requests; its test/test-support source-path check is zero. The
C99 route uses 2,128 independently clean-gated FFmpeg production files; the
others use the corresponding LLVM production source pools. Candidates without
a safe source anchor or a clean witness are not sent to the model. All queued
output remains excluded from the snapshot until it passes the paired-source,
no-test-source, portable Injector, and exact-primary-diagnostic gates.

**Evidence-backed C++23 exception route (2026-08-04).** The target selector
previously treated several TableGen names containing words such as
`category`, `wasm`, `ptrauth`, or `x86` as special-mode-only. The pinned
Clang test scan records eight of these types under ordinary
`-x c++ -std=c++2b` commands with no target or feature flag. The selector now
admits only that explicit eight-name set to the ordinary C++23 route. A
separate batch contains 24 requests (three independently clean-gated LLVM
production TUs per type) for those eight current strict gaps. This selection
change does not alter the strict snapshot: a type enters only after Gemma
produces a portable Injector and exact compiler replay creates a paired
non-test record.

**Objective-C real-source route (2026-08-04).** The generator now preserves
`objective-c` and `objective-c++` as truthful source-language labels, including
the temporary-file suffix and C/C++ driver selected by the verifier. A fresh
`libobjc2` production checkout was configured with the pinned patched Clang:
all **30 / 30** non-test translation units clean-gated, including five
Objective-C and three Objective-C++ sources. Clang-test trigger metadata was
then used as prompt-only evidence to identify **87** current strict gaps that
need only an Objective-C-family language mode (77 Objective-C++, 10
Objective-C), with no target, ARC, Blocks, runtime, or other feature flag.
All **77** Objective-C++ candidates are now materialized in ten deterministic
batches: 231 real-source witnesses (three independently clean-gated `libobjc2`
production sources per type) and 77 direct Injector requests, with no repeated
target name or test-source path. Their local Gemma-4-31B Injector-synthesis and
replay jobs are serialized behind the existing one-node queue. They remain
excluded from strict coverage until the same paired-source, no-test-source,
portable-Injector, and exact-primary-diagnostic gates accept an actual replay
result. Of the ten bare Objective-C candidates, eight share their diagnostic
name with the Objective-C++ route; the two remaining distinct names are bound
to three clean Objective-C production TUs each and queued after that route.
Four more test-only names use a separately re-clean-gated Objective-C++ mode:
three require MS extensions and one requires both Blocks and MS extensions.
The verified mode flags are included in the model's Injector request and all
four jobs are serialized after the bare-language route.

The audit also corrects an input-discovery omission: it includes the
compiler-verified first witness produced when a portable Injector is applied
to its real source, rather than counting only later replay files.  Cross-source
replay remains separately reported and is not used as a substitute for that
core paired-data validation.  Active 53--64-target local-Gemma campaigns use
resumable 45-minute slices and retain only exact target-diagnostic outcomes.

The full-catalog figure is the authoritative operational metric for expansion
and gap discovery. The frozen **1,935-diagnostic strict C/C++ code scope** is
the paper headline: it is derived from the same exact audit by applying the
audited invocation/environment and dialect/target exclusions. Both views
source-clean-gate every parent TU, require an exact typed compiler diagnostic
after Injector replay, and record the resulting paired source.

The target is now attained by the fresh full-catalog strict-audit artifact.
Queued campaigns remain useful for multiplicity and later data-scale work, but
they are not required to establish this coverage milestone.

**Objective-C real-source extension (staged, not counted; 2026-08-04).**  The
clean-source gate now accepts Objective-C and Objective-C++ translation units
as first-class languages.  A clean `libobjc2` production pool contains 30
non-test TUs (5 Objective-C and 3 Objective-C++, in addition to C/C++ files),
each with its project build command and a compiling `corrected_src`.  Three
serial local-Gemma batches are staged behind the existing one-node queue:
one source-prechecked C++23 availability target (3 requests), 10
Objective-C targets over three independent real source witnesses each (30
requests), and 20 Objective-C++ targets over three witnesses each (60
requests).  The latter 20 target names are current strict gaps and are
Clang-test-reachable; 18 have compact prompt-only test/emission evidence and
the remaining two retain TableGen and source context.  No test source is
eligible for these requests.  These batches are explicitly **pending**:
their outputs will be added only after portable-Injector replay produces an
exact primary diagnostic on the paired non-test source.  They do not change
the 1,177/3,891 strict snapshot or any CSV total above.

## Clang Regression-Test Reachability Audit (2026-07-26)

Clang tests are used here strictly as **coverage evidence**, never as FuzzLang
records or source material. A fresh direct scan of 21,359 C/C++/ObjC-family
test files under the same patched `llvmorg-22.1.8` compiler found 1,371 catalog
error diagnostics. Against the then-current strict FuzzLang set of 1,000,
617 overlapped this test-derived set; 754 were test-only, and 383 were
FuzzLang-only. These are historical scan-stage counts, superseded by the
current 1,044-type comparison below.

The scan was then extended beyond ordinary frontend invocations. Replaying
`%clang`/`%clangxx` driver commands increased the test-derived total to 1,377
but reproduced none of the 383 FuzzLang-only diagnostics. A separate 1,080
file, three-batch scan of `%clang_analyze_cc1` and `%clang_cl` modes found 99
catalog errors and likewise reproduced **0/383**. These results are recorded
under `data/gen/experiments/clang-test-*-scan-20260726/`.

The module/PCH follow-up now runs **real lit**, rather than a one-file replay:
1,546 tests ran in four 500/500/500/46-file batches with the pinned patched
Clang. It observed 59 catalog error diagnostics and reproduced one of the 383:
`err_non_template_in_template_id`. Therefore the currently un-reproduced set
is **382**, not 383. Three batches have non-zero lit exits because this
minimal Clang-only build lacks unrelated optional tools/features; compiler
stderr was retained and only typed `err_*` diagnostics were counted.

The finalized union over every completed scan mode is **1,444** distinct Clang
test-reachable diagnostics. Recomputing it against the current strict 1,178
FuzzLang types gives an overlap of **779**; there are therefore **665
Clang-test-only** types and **399 FuzzLang-only** types.  These three exact
name lists and their checksummed summary are stored
in `data/gen/experiments/clang-test-reachability-audit-20260726/`.

The first expansion campaign began from the then-current 799 Clang-test-only
names. Its completed standard/mode-routed, C++11, ordinary-C++23, and
cross-target follow-ups added 104 new strict types, leaving 695 at that
intermediate point for subsequent routing. It supplies Gemma-4-31B with TableGen
definitions, Clang-test trigger evidence (as prompts only), and clean
real-source snippets.  Generated Injectors are
then applied only to those non-test sources and compiler-verified in bulk; no
Clang regression-test source is eligible to become a FuzzLang record.

This still is not a claim that Clang's entire suite cannot reach all 399
remaining kinds: HLSL DXC tests use a distinct driver, and remaining lit modes
may require optional tools/features absent from the minimal build. They must
be executed through lit rather than approximated by a one-file syntax scan.

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

Historical Breadth composite coverage (**not** the paper headline — that is
1,208/1,935 from the release-union audit, which applies the strict admission
gate this composite predates):

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
Week-2 FuzzLang DSL gate, including transfer to a second C++ project. They are
also the clearest existing evidence for the cost claim: 896 records on 428
unseen LLVM TUs and 97--100 exact-target records on held-out Abseil, all with
**zero model or API calls**. The remaining work is to turn them into a released
multi-project measurement (E1) and to establish dataset value by SFT (E3).

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
a merged training release, nor the released multi-project zero-cost replay
measurement.

The checked-in request builder makes the next queue reproducible from a
TableGen gap list and verified clean production code. Its optional archived
recipe input only retrieves a real syntax shape; no recipe edit is passed to
Gemma or reused as an Injector.

**TP=8 Clang-test-guided expansion (2026-07-27).** A single Tioga node was
used as one eight-logical-GPU vLLM tensor-parallel server (not eight independent
workers and not a multi-node job). It processed 459 distinct Clang-test-grounded
requests in 64-request bounded batches with two candidates and one feedback
round. The archived campaign at
`data/gen/experiments/clang-only-gemma-injectors-v0001/gemma-vllm-tp8-clang-test-v0001/`
contains 1,030 candidate attempts, 489 syntactically valid Injector artifacts,
and **403 distinct target diagnostics**. Every request carried regression-test
trigger text only as prompt evidence; this is a synthesis-candidate milestone,
not a compiler-verified record or coverage claim. A batched paired-source
compiler replay is the next gate.

**Interrupted strict replay (2026-07-27).** The replay used one CPU-only Flux
allocation on one Tioga node (`-N1 -n16`, zero GPUs), not independent node
jobs. Its 16 in-node ranks deterministically partitioned all 489 candidate
Injectors and routed each rank only to the clean, non-test LLVM C++23 source
files named by its witnesses; all 773 witness source identities are present in
the canonical 1,992-TU pool. The task was externally cancelled after 13
minutes, so this is an incomplete checkpoint rather than a completed campaign:
it retained 1,608 strict compiler outcomes, with candidates rejected for
compiling clean or emitting a different typed diagnostic, and one strict paired
record for `err_atomic_specifier_bad_type` from
`llvm/lib/Support/BuryPointer.cpp`. Each accepted output must pass the
clean-parent gate and have a primary typed diagnostic name exactly equal to the
Injector target. The checkpoint is not a final yield or a coverage update;
only a completed replay manifest can support those claims.

**Compiler-feedback retry and verification (2026-07-27).** A follow-up retry
selected 63 targets from the interrupted replay that had emitted a wrong or no
typed diagnostic. Gemma-4-31B generated 189 schema-accepted candidates and 73
unique Injector artifacts in one single-node TP=8 run (one process, eight
logical GPUs); these remain candidates, not coverage. The resulting 73
Injectors are now being checked in one separate CPU-only, single-node
16-process batch against clean paired sources (zero GPUs, at most 50 compiler
attempts per Injector). The launcher now forcibly ends the local vLLM process
group after a bounded graceful shutdown so a completed generation run cannot
hold its node. The fragment-generation route additionally rejects any direct
copy of a substantive Clang-test line; tests are prompt evidence only.

**Append-fragment expansion checkpoint (2026-07-27).** The lexical retry was
fully replayed in 16 CPU ranks and produced zero exact-target paired records,
so it is retained as negative evidence rather than counted as coverage. The
replacement route asks Gemma for a self-contained schema-v2 append fragment,
with Clang-test text used only as prompt evidence. The parser now restores only
request-determined JSON boilerplate that Gemma sometimes omits (schema, target
identity, language, and the location of `operation`); explicit conflicting
values are still rejected, and compiler replay remains the semantic gate. Its
first complete batches accepted 499 of 512 candidates spanning 252 target
diagnostics, before the single-node TP=8 job was externally cancelled. This is
a resumable generation checkpoint, not strict coverage: no append candidate is
counted until a clean production parent and exact primary diagnostic have been
compiled and recorded.

**Completed append-fragment strict replay (2026-07-28).** Three completed one-node CPU-only replays (16 local compiler processes, zero GPUs) tested the append-fragment candidates against clean, non-test LLVM C++23 translation units. Across the three rounds, the exact-target union is **184 distinct diagnostics** and 313 paired records: round 1 retained 260 records / 153 types; compiler-feedback round 2 retained 41 / 23 new types; an eight-candidate round 3 retained 12 / 8 new types. These are the only numbers counted as strict coverage from this expansion. Candidate counts are deliberately reported separately: the first append round safely normalized 880 Injectors spanning 451 targets; feedback rounds safely normalized 386 and 440 Injectors. The third round has sharply diminishing yield, so the next expansion work is to recover Clang-test run modes and target/feature parameters for the remaining test-only diagnostics, not to repeat the same default-C++23 prompt. Test excerpts remain prompt-only evidence, and every retained record has a verified clean production parent.

**Mode-routed adaptive replay (2026-07-28).** Gemma-4-31B-it generated 664 distinct append-fragment Injectors from 253 standard requests, each carrying two distinct clean production-code windows and bounded Clang-test evidence. A one-node, TP=8 generation run produced 2,056 candidates; GPUs were released before validation. The mode audit selected 522 host-replayable Injector/mode pairs (C++98/11/14/17/20/2c, Blocks, and MS extensions); a one-node CPU-only replay admitted 29 paired records representing **17 diagnostic types not present in the immediately preceding mode-replay set**. The useful yield came primarily from C++98/11/14. These numbers are deliberately local to this adaptive mode-routed experiment and must not be added to any earlier global total without a full union/dedup audit.

**Test-gap batch 1 (2026-08-04).** A new Gemma-4-31B campaign began with
the Clang-test-only strict gap list, but used test material only as prompt
evidence.  Each request was bound to a clean, non-test LLVM or FFmpeg source
file in a compatible compiler mode; every admitted result has a paired
`corrected_src`, a portable Injector, and an exact primary typed diagnostic.

| mode | target requests | strict records / types |
|---|---:|---:|
| C++17 | 11 | 3 / 3 |
| C++23 | 63 | 34 / 34 |
| C11 | 7 | 5 / 5 |
| C23 | 25 | 16 / 16 |
| OpenMP | 42 | 2 / 2 |
| MS extensions | 14 | 2 / 2 |
| Blocks | 3 | 0 / 0 |

The 62 accepted target types are mutually distinct and absent from the prior
strict audit.  The new full-union audit reports **1,106/3,891** covered TableGen
error diagnostics, **6,848** strict records, and **8,608** portable Injectors.
OpenMP and Blocks are retained as useful low-yield mode evidence rather than
being silently dropped; their remaining targets need directive-/structure-aware
Injector synthesis.

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

**Complete (2026-08-14): E5, the FuzzLang data-scaling curve.** The same arm at
nested sizes 557 / 1,500 / 4,000 from the de-vendored pool, everything else held
fixed, on the same two cohorts. Protocol was fixed in advance
(`data/reports/e5-scaling-protocol/`); results in
`data/reports/e5-scaling-20260814/`.

| cohort | 557 | 1,500 | 4,000 | base |
|---|---:|---:|---:|---:|
| unseen file | 0.787 | 0.827 | **0.893** | 0.167 |
| unseen project | 0.687 | 0.813 | **0.853** | 0.060 |

**Still rising at 4,000 on both cohorts and on exact match**, every step larger
than E3's seed spread. At 4,000 the intervals are disjoint from DirectEdit's
557-record result on *both* cohorts (0.893 vs 0.642; 0.853 vs 0.711), so **E3's
unseen-project tie was an artifact of the shared budget** — 557 records is what
DirectEdit could afford, not what FuzzLang costs.

**Correction it forced.** At the matched 557 budget the de-vendored arm scores
**0.687** on unseen projects, not E3's 0.736, and slightly below DirectEdit's
clean 0.711 with overlapping intervals. E3's figure is consistent with its 31
vendored Abseil training records helping on a 45-instance Abseil cohort, though
draw variance is not excluded. **0.736 should not be quoted**; FuzzLang's
unseen-project case rests on the scaling curve, not the matched row. The
unseen-file result is unchanged (0.787 vs 0.780).

The tiers also widen coverage as they grow (239 → 319 → 392 diagnostics,
501 → 1,081 → 1,789 source files), so "more data" here means more *diverse*
data; separating volume from diversity needs a further experiment. One seed per
tier bounds the direction but not the exact heights.

The revised paper requires four paper-level results that remain incomplete:

1. **Multi-project construction result (E1): first release complete
   (2026-08-08), recounted without vendored source (2026-08-12).** The released
   library was replayed over 13 clean, non-test projects with splits frozen
   beforehand, producing **13,007 verified records over 514 diagnostics (459 in
   paper scope) from 3,714 source TUs, with 395 diagnostics at multiplicity ≥ 3
   — using zero model calls and zero GPU hours**. On the four projects held out
   entirely (Abseil, FFmpeg, leveldb, json-c) the lexical library produced 2,325
   records over 138 diagnostics in 139 seconds on one node. 395 lexical-train
   Injectors each reached 11.7 source TUs on average and 110 crossed a project
   boundary. All records pass the invariant audit with zero violations. See
   `data/reports/e1-construction-20260812-devendored/`; the 08-08 report is
   superseded for every count.

   Folding these records into the canonical audit raises the released strict
   coverage headline to **1,208 / 1,935 (+13)** and cuts the types that rest on
   opportunistic relabelling alone from 47 to 34 — see
   `data/reports/strict-coverage-20260812-release-union/`, whose
   `coverage_numbers.csv` states which of the four circulating figures to quote
   where.
   Remaining: raise RealSource strict coverage from 459/1,935 toward the ~1,000
   goal, and merge the accepted records into a frozen training release.
2. **Gemma SFT result (E3): complete (2026-08-11).** Three arms matched at 557
   records and exactly 260,751 rendered tokens, three seeds each, 150-instance
   cohorts, zero eval leakage on six dimensions. Verified repair on unseen files:
   **FuzzLang 0.780 [0.740, 0.818] > DirectEdit 0.642 [0.598, 0.684] > Base
   0.167 > Mechanical 0.020**. Exact match 0.538 / 0.378 / 0.007 / 0.009.
   Mechanical-SFT is *worse than no fine-tuning*, losing 25 of 26 decided pairs
   to the base model despite having the lowest training loss — the control that
   shows the gain is not "more tokens". See
   `data/reports/e3-sft-value-20260811/`.
3. **Generalization result (E3, unseen project): complete (2026-08-11).** On
   Abseil/FFmpeg/leveldb/json-c, none of which contributed a training record,
   verified repair is **FuzzLang 0.736 vs Base 0.060**, and the transfer also
   crosses a language boundary (FFmpeg and json-c are C; training is mostly
   C++). Against DirectEdit the full-cohort intervals overlap (0.736 vs 0.711) —
   a tie on unseen projects, with exact match still favouring FuzzLang (0.542 vs
   0.416).

   **Corrected 2026-08-13.** This entry previously cited "excluding Abseil,
   FuzzLang 0.737 vs DirectEdit 0.638" as the trustworthy number. Withdrawn.
   **61 of 68 diagnostics in this cohort occur in exactly one project**, so the
   per-project and per-diagnostic breakdowns are the same table — diagnostic mix
   predicts every per-project rate to a mean absolute residual of 0.010, and on
   the 7 diagnostics Abseil shares with leveldb (the only place the factors
   separate, n=11 vs 15) both differences straddle zero. This also resolves the
   open "Abseil anomaly": DirectEdit's 0.881 there is its diagnostic mix, not
   the project. Excluding Abseil is still justified as contamination control,
   but it changes the diagnostic mix at the same time and is not the same
   comparison minus contamination. See
   `data/reports/e3-project-confound-20260813/`.
4. **NatErr result (E4): pipeline complete and correct, release at 3 of
   100–300 (2026-08-12).** Harvest → reproduce → formalize now runs end to end
   on an up-to-date local LLVM checkout, and every gate it applies is one the
   paper needs. Funnel: **2,039** reachable fix-build candidates → **682**
   self-contained single-file fixes → **163** with a reproduced typed primary
   diagnostic → **3** whose fix side also compiles clean. All 3 are isolated
   from the SFT training arms. See `data/reports/e4-naterr-20260812/`.

   **Scarcity is itself a result.** Fix-build commits over full local history:
   llvm 2,039 (since 2022-06), ffmpeg 81 (all time), abseil 3, json-c 2,
   leveldb 2. Outside one very large, very fast project there is nothing to
   mine — the argument for a construction framework, in someone else's data.
   It also forces the project choice: LLVM is the only viable source *and* the
   largest training contributor, so `real/naterr_isolation.py` enforces
   file-level isolation explicitly (0% overlap with the current arms; 67% with
   the full E1 pool, so the gate must be rerun against whatever arms a scaled
   SFT run actually uses).

   **Scaling this was costed, then tested, and is not recommended.** A snapshot
   campaign was built (`run_naterr_snapshot_campaign.sh`, deterministic
   set-cover plan, Flux sharding) and priced at 46 node-hours for ±3-day
   windows. Before spending it, the premise underneath the funnel was tested
   directly: **does a fix-build commit's predecessor fail to compile in its own
   environment?** At the exact predecessor commit, no — the candidate compiles
   cleanly, and its fix was `+#include <atomic>`, a break only on a standard
   library lacking the transitive include. In a ±3-day window, 5 candidates
   produced 0 reproductions and 2 clean compiles. The 163 "reproduced" were in
   the main artifacts of compiling historical source against a mismatched
   header tree.

   **The mechanism is the finding.** A large project's pre-merge CI covers the
   mainstream configuration, so what survives into `main` and needs a follow-up
   "fix build" commit is exactly what that CI misses — another compiler,
   another standard library, another platform, another build system. Natural
   compilation errors are therefore not only scarce but **environment-bound**:
   reproducing one costs a configuration matrix, not a git checkout. Combined
   with §1's scarcity table, this is the measured case for constructing errors
   rather than mining them, and it belongs in the paper. A future NatErr
   attempt should invert the premise — fix one configuration, then search
   history for errors reproducible in it.

   Three defects were found and fixed on the way: `-Werror` plus GCC-only
   `-Wno-*` suppressions rejected 240 of 269 candidates by failing the *fixed*
   revision; 672 of the archived manifest's 856 SHAs no longer exist in `main`
   (GitHub squash-merges rewrote them), so candidates are re-harvested locally;
   and formalization is now parallel, with a test asserting byte-identical
   output at any worker count.

**Contamination found and fixed (2026-08-11).** duckdb and protobuf vendor
Abseil under `build/_deps/absl-src/`, and the clean-source gate excluded test
paths but not fetched dependencies, so Abseil source entered training labelled
as duckdb/protobuf while Abseil was a held-out evaluation project (FuzzLang 31
records, Mechanical 26, DirectEdit 0). Content hashing missed it because the
vendored revision differs from the standalone checkout; only project-identity
analysis of the path found it. `is_vendored_path()` now rejects fetched
dependency trees and generated unity-build stubs at three points in the gate.
Applying it to the current pools removes 507 of 1,196 sources (352 of duckdb's
391, 153 of protobuf's 464).

**E1 recounted (2026-08-12).** `run_e1_construction_report.py --exclude-vendored`
recounts every arm from its records rather than from the manifests written at
generation time. 2,090 of 15,097 records were vendored, confined to three
projects: duckdb 1,941 → 167, protobuf 1,199 → 891, yaml-cpp 91 → 83. Ten
projects and both held-out arms are untouched, and every release target still
holds. See `data/reports/e1-construction-20260812-devendored/`.

**Behaviour audit of E3 (2026-08-12).** "Verified fix" means the TU compiles,
which a delete-to-compile output also satisfies, so every archived generation
was re-read for edit-shape degeneracy. **93–96% of FuzzLang's verified fixes
survive**: non-degenerate rates 0.729 (unseen file) and 0.709 (unseen project)
against DirectEdit's 0.598 and 0.676 — ranking unchanged, unseen-project margin
widened. Zero large deletions and zero empty repairs across all 20
configurations. Two further findings:

- Degeneracy tracks the **injector operation, not the generator**: `insert`
  tasks degenerate at 1.3–2.2% for both arms, `replace` tasks at 13–32% for
  both. A `replace` overwrites the original statement, which then appears
  nowhere in the model's context, so the inverse repair task is genuinely
  under-determined and deletion is a defensible compiling answer. The library is
  5,615 `replace` / 2,570 `insert` / 1,525 `append` / 50 `delete`, so the
  release manifest must mark `replace`-derived records as under-determined for
  *repair* evaluation — they remain valid *construction* records.
- The Mechanical control is explained: its reference repair is **one character
  wide at every quartile** (FuzzLang 25/54/87, DirectEdit 11/23/52, evaluation
  ≈43–46), so the loss-minimising policy is the identity map and **67.6% of its
  predictions are byte-identical to their input**. Its lowest-in-class training
  loss and its 2% repair rate are the same fact: matching the token budget does
  not match the learning signal.

See `data/reports/e3-quality-audit-20260812/`.

**Retired (2026-08-08):** "a matched comparison of Injector reuse against direct
per-record Gemma editing" was previously listed first here. It is withdrawn. It
staged a near-zero-cost offline tool against a 31B model at *generating* errors,
which the model naturally wins and which says nothing about the dataset's value.
A model-based generator now appears only as an equal-budget training-data
baseline inside result 2. The withdrawn experiment, its numbers, and the harness
defect it uncovered are recorded in `docs/E1-dataset-construction.md`.

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


### Cross-target strict Injector replay (2026-07-28)

- Extracted 104 mutually exclusive C++ Injector replays from the adaptive Gemma
  batch using the exact `-triple` flags found in the corresponding Clang test
  `RUN:` lines.  `%itanium_abi_triple` was resolved from this build's
  `lit.site.cfg.py` to `x86_64-unknown-linux-gnu`; no platform or ABI was
  silently substituted.
- Re-clean-gated a production LLVM source under four additional exact targets
  (`x86_64-linux-gnu`, `x86_64-unknown-linux-gnu`, `i386-linux`, and
  `i386-apple-darwin9`), each with one accepted clean source.
- Ran the 104 replay attempts in one Flux allocation (one node, 8 CPU cores,
  no GPU, no nested or additional jobs).  Strict primary-diagnostic equality
  yielded 2 paired core records: `err_sizeless_nonlocal` on `arm64-linux-gnu`
  and `err_need_header_before_typeid` on `x86_64-unknown-linux-gnu`.  Both are
  new relative to the immediately preceding mode-routed replay; the local
  mode-plus-target union is now 19 distinct diagnostic names.
- The remaining 100 attempts were rejected exactly as intended: 65 emitted a
  different primary diagnostic and 35 compiled cleanly.  This is a local
  incremental result, not a replacement for the pending global deduplicated
  coverage audit.
