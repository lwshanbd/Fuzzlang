# Design: real-code error injection (`gen/realcorpus/`)

**Date:** 2026-07-05
**Status:** approved for planning
**Author:** FuzzLang (Baodi Shan) + Claude Code session

## Motivation & hypothesis

The current Gen corpus is AI-generated *toy snippets* (10–40 lines) that are
mechanically or model-mutated to produce a compile error. The first repair
experiment (metric #2) showed the loop drives the whole effect (b0 72% → any
loop 93%) while the **typed diagnostic signal buys nothing over raw stderr**
(diag − b1 = +0.1 pts, within noise). The most likely reason: on tiny
single-diagnostic programs, `stderr` already carries the fix; there is no
complex context to navigate and no error cascade to disambiguate.

**Hypothesis:** inject errors into *real, complex* code (LLVM translation units)
and the picture changes. Real TUs are large and their errors **cascade**
(one root bug → 10–30 follow-on errors). That is exactly the regime where the
structured diagnostic should help: `b1` sees a wall of cascade noise, while
`diag` extracts the clean primary diagnostic. We expect **diag − b1 to grow
with cascade depth**.

## Ordering: target-first (diagnostic-driven)

**This is the load-bearing design decision.** The pipeline is **target-first**,
not snippet-first:

- **Target-first (this design):** the driver is the **list of target
  diagnostics**. For each error A, *find* a real fragment where A is inducible,
  then inject a bug that triggers A. The diagnostic is a controlled *input*.
- **Snippet-first (rejected):** sample a region, inject whatever bug is natural,
  observe whatever diagnostic emerges. The diagnostic is an emergent *output*;
  coverage is uncontrolled.

Target-first is chosen because FuzzLang is a *compiler-diagnostic-driven*
framework: the diagnostic catalog is the denominator and the driver everywhere
else (Coverage⟷Gen is a closed loop). Target-first keeps the real-code corpus
inside that loop, gives control over *which* errors we produce (balanced family
distribution for the cascade × family analysis), and generalizes to
train/coverage expansion without a redesign. *(This supersedes an earlier
snippet-first "realistic any-family" sketch.)*

## Goal & scope

Decided levers (brainstorming, 2026-07-05):

- **Goal:** build a real-code-sourced **eval slice** first (validate cheaply),
  expandable to train/dev + coverage-filling later.
- **Ordering:** **target-first** (above).
- **Target set:** the **full in-scope catalog** (~1935 diagnostics), driven in
  **inducibility-priority order**. A budget cap defines the first eval slice
  (the highest-yield prefix); the driver itself is the whole catalog.
- **Injection:** model-assisted **semantic** bug via **Approach A —
  region-scoped localized edit** (edit a selected fragment, not the whole file),
  primed with a **few-shot exemplar** of how the target was triggered elsewhere
  (pulled from the existing 13,745-record dataset). Model = **`gpt-5.4-mini`
  only** (no gpt-5.5 without explicit per-task permission).
- **Error shape:** accept **both** single-error and cascade instances; **tag
  cascade size**; also tag whether the emitted **primary == target** diagnostic.

**In scope:** the `gen/realcorpus/` module; a runnable emitting an eval-slice
JSONL in `run_sweep` input format; tests. **Out of scope (future):**
exhaustively pushing the full catalog for coverage; regenerating train/dev;
history-anchored injection; non-LLVM corpora.

## Architecture

New self-contained package `src/gen/realcorpus/`. Driver = target diagnostics;
corpus = a **feature-indexed searchable pool** of real fragments.

```
in-scope catalog  ──(inducibility-priority)──► target diagnostic A (name + message)
                                                   │
  ┌── FragmentIndex (built once) ────────────┐    │ ① SELECT: rank fragments by
  │ clean LLVM TUs → functions/regions,      │◄───┤   feature-relevance to A;
  │ each tagged with cheap syntactic features│    │   take top-K candidates
  └──────────────────────────────────────────┘    ▼
                                    ② INJECT: gpt-5.4-mini, given (A + its exemplar
                                       trigger + fragment), returns a MINIMAL edit
                                       that should trigger A — or "not applicable"
                                       → try next candidate
                                                   ▼
                                    ③ VERIFY with the real per-file compile cmd:
                                       keep iff a real error results; tag
                                       primary==A and cascade_size
                                                   ▼
                                    ④ EMIT Record → next target (or next A-instance
                                       until per-target cap)
                                                   ▼
                              ⑤ run_realcorpus.py → eval-slice JSONL (run_sweep fmt)
                                                   ▼
                              ⑥ (existing) run_sweep b0/b1/diag → aggregate_eval,
                                 sliced by cascade depth and by primary==target
```

### Components & interfaces

| unit | responsibility | key interface | reuses |
|---|---|---|---|
| `compile_db.py` (shared) | parse `compile_commands.json`; portable-ize a recorded command | `load_compile_db(path)`; `build_clang_argv(entry, clang, src)` | **extracted** from `real/reproduce_stage2_llvm.py` |
| `corpus.py` | build the fragment pool from clean TUs; tag features | `build_fragment_index(db, verifier, *, n_files, seed) -> FragmentIndex`; `Fragment=(rel_path, tu_src, span, features, compile_cmd)` | `FuzzlangClangVerifier`, `region.py` |
| `region.py` | split a clean file into candidate spans (functions) | `select_regions(src, *, max_regions) -> list[span]` (brace scan; string/comment-masked) | `mutate/_scan.py` |
| `features.py` | cheap syntactic tags per fragment + per target | `fragment_features(text) -> set[str]`; `target_features(name, msg) -> set[str]` | — |
| `targets.py` | build the ordered target list + per-target exemplar | `iter_targets(catalog, out_of_scope, dataset) -> Iterator[Target]` (Target = name, msg, exemplar_edit, priority) | `diagnostics.catalog`, existing dataset |
| `select.py` | rank fragments for a target | `rank_fragments(target, index, *, k) -> list[Fragment]` | `features.py` |
| `prompt.py` | build injection messages; parse the edit | `build_inject_prompt(target, fragment_text, file_head)`; `parse_edit(reply) -> Edit|None` | — |
| `inject.py` | one model call → applied erroneous source, or None | `inject_target(target, fragment, chat) -> str|None` | `chat_backend` |
| `collect.py` | verify + emit | `collect_real_record(fragment, erroneous_src, target, verifier) -> Record|None` (sets `cascade_size`, `primary_matches_target`) | `foundation.record`, verifier |
| `run_realcorpus.py` | CLI: drive targets, budget-capped → JSONL | args below | `prepare_eval`-style conversion |
| `tests/` | TDD, `MockVerifier` + mock chat | — | — |

**Feature relevance (the SELECT heuristic).** `features.py` maps both fragments
and targets into a small tag vocabulary (`template`, `overload/call`, `pointer`,
`class/member`, `constexpr`, `enum`, `cast`, `lambda`, `narrowing`, …). Target
tags come from keyword-matching the diagnostic name/message
(`err_ovl_no_viable_function` → `overload/call`); fragment tags from a cheap
scan. `select.py` ranks fragments by tag overlap so INJECT is tried on
plausibly-inducible fragments first. Heuristic, not exhaustive — misses fall
through to lower-ranked candidates within the per-target budget.

**Exemplar priming.** `targets.py` pulls, per diagnostic A, one exemplar from
the existing dataset (its `erroneous_src` + the recorded mutation/edit) and
passes it to `prompt.py` as a few-shot hint. This sharply raises inducibility
and links the toy and real datasets. Targets are ordered by an inducibility
prior: **prior-covered diagnostics first** (they are known-inducible somewhere),
then the rest.

### Data flow & schema

Each emitted `foundation.record.Record`:

- `corrected_src` = the **real, clean** TU text (the whole file — full compile
  context for the repair model, bounded by file size).
- `erroneous_src` = the TU with the model's localized edit applied.
- `diagnostics = (primary DiagInfo,)` — first `error:` + `DiagID`, name via
  `diagtool`.
- `provenance = Provenance(origin=Origin.GUIDED, source="llvm:<rel_path>",
  detail={"strategy": "realcorpus_inject", "target_diag": A.name,
  "primary_matches_target": bool, "cascade_size": int, "region": span,
  "edit": "<old→new summary>"})`.
  (Reusing `Origin.GUIDED`; a dedicated `Origin.REAL_INJECT` is a possible
  follow-up — decide during planning.)
- `language` from the TU extension; `split = EVAL`.

`run_realcorpus.py` writes rows directly in the **`run_sweep` input format**
(`instance_id, buggy_src, corrected_src, compile_cmd, diag_id, diag_name,
language, cascade_size, target_diag, primary_matches_target`) so metric #2 runs
with no adapter.

### Injection prompt contract (Approach A, target-first)

- **Input to model:** target A (name + message), A's exemplar trigger, the
  selected fragment text, and a short file-head slice (includes / usings /
  nearby types). Instruction: introduce **exactly one** minimal edit to this
  fragment that makes clang emit **A**, staying faithful to the surrounding
  code; if A cannot be naturally induced here, reply `NOT_APPLICABLE`.
- **Output:** a minimal edit `<<<OLD … === NEW … >>>` with a unique `old`
  anchor, or `NOT_APPLICABLE`.
- **Apply:** locate the unique `old` in the full TU, replace with `new`. Reject
  if absent/non-unique → next candidate.
- **Verify:** compile with the real cmd. Keep iff original compiled clean (from
  ①) and erroneous errors with a parseable primary. Record `cascade_size` and
  `primary_matches_target` (primary DiagID == A). A near-miss (real error but
  primary ≠ A) is still a valid repair instance — kept and tagged, not
  discarded.

### CLI (`run_realcorpus.py`)

```
PYTHONPATH=src python3 src/gen/realcorpus/run_realcorpus.py \
  --compile-db /p/lustre2/shan4/fuzzlang-llvm-build/compile_commands.json \
  --llvm-src   external/llvm-project \
  --clang-bin  $FUZZLANG_CLANG_BIN --diagtool-bin $FUZZLANG_DIAGTOOL_BIN \
  --dataset    data/gen/splits/train.jsonl   # exemplar source \
  --out-of-scope data/gen/out_of_scope.txt \
  --model gpt-5.4-mini --base-url https://api.openai.com/v1 \
  --n-files 300 --per-target 1 --candidates-per-target 4 --retries 2 \
  --max-instances 300 --workers 16 \
  --out data/gen/splits/eval_realcorpus.jsonl
```

`--max-instances` is the budget cap that bounds the first slice; the driver
iterates the full in-scope catalog in priority order until the cap or the
targets are exhausted.

## Compile environment & LLVM-version consistency

The **one-LLVM-version** hard rule (`llvmorg-22.1.8`) applies to the corpus, the
compile commands, and the patched clang. The existing `compile_commands.json` at
`/p/lustre2/shan4/fuzzlang-llvm-build/` may be from LLVM `main` (Stage-2 cloned
`--branch main`). **Planning must first verify** the DB's source root; if not
the pinned tree, **regenerate** from `external/llvm-project` (ca7933e = 22.1.8)
with `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON` (one-time ~30–60 min build on pdebug;
build the `clang` target so generated `.inc` headers exist).

**Reproducibility caveat:** recorded commands carry machine-absolute `-I`
paths → the eval JSONL is reproducible on *this* build tree, not portable.
Acceptable; note in the dataset README.

## Testing (TDD, test-first)

- `compile_db.py`: parse a fixture DB; `build_clang_argv` drops `-o`, strips the
  recorded source path, forces `-fsyntax-only -fno-color-diagnostics`, appends
  `__SRC__`. Characterization test that `reproduce_stage2_llvm` is unchanged
  after the extraction.
- `region.py`/`features.py`: brace scan finds function spans and ignores
  strings/comments; feature tags fire on the right constructs.
- `targets.py`: ordered targets exclude out-of-scope; each carries an exemplar
  when the dataset has one; prior-covered sort first.
- `select.py`: fragment ranking prefers tag-overlapping fragments.
- `prompt.py`: `parse_edit` reads `<<<OLD/NEW>>>`; handles `NOT_APPLICABLE` and
  missing/non-unique anchors.
- `inject.py`/`collect.py`: with `MockVerifier` + mock chat, a scripted edit
  that errors emits a `Record` with correct `cascade_size` and
  `primary_matches_target`; a still-compiling mutant emits nothing; a clean
  original is required.

## Success criteria

1. **Builds:** `run_realcorpus.py` emits ≥ ~150 verified real-code instances
   across a spread of target diagnostics, with a non-trivial cascade-size
   distribution; per-target yield reported honestly.
2. **Experiment:** re-run `b0/b1/diag` (matched budget, 3 seeds) on the slice;
   report fix-rate **sliced by cascade depth** and by `primary_matches_target`.
   The module **succeeds as a research artifact whether or not** diag − b1
   widens — a null result on real code is itself a finding. The pass bar for the
   module is: verified, reproducible, honestly-measured real-code instances.

## Risks & mitigations

| risk | mitigation |
|---|---|
| compile DB is `main`, not 22.1.8 | verify first; regenerate from pinned tree |
| **low inducibility** for much of the catalog (target-first's core cost) | exemplar priming; feature-ranked SELECT; bounded candidates/retries per target; drive in inducibility-priority order; **report per-target yield, don't hide misses** |
| model returns `NOT_APPLICABLE` / unappliable edit | try next candidate; per-target budget cap; count and move on |
| primary ≠ target (near miss) | keep as a valid instance, tag `primary_matches_target=false` |
| large TUs slow to compile (~1–5 s) | sample fragments; `--workers`; `-fsyntax-only` |
| absolute `-I` paths non-portable | documented; eval runs on this tree |
| cost | region-scoped I/O, `gpt-5.4-mini`, `--max-instances` cap |

## Out of scope / future

- Exhaustively pushing the full catalog for real-code coverage (phase 2b).
- Regenerate train/dev from real code (phase 2c, if the slice shows signal).
- History-anchored injection using `real/` manifests.
- Non-LLVM corpora; a dedicated `Origin.REAL_INJECT`.
