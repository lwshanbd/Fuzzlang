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

The essential realization: `gen/collect.py:collect_records(correct_src, …)`
mutates a *string* and verifies it — it does not care where the string came
from. Today that string is a toy snippet with a generic `-std=c++17` command.
This design feeds it **real LLVM TUs + their real per-file compile commands**
instead. The mutation/verification/record-emission discipline is unchanged;
only the *source of correct code* and the *injection method* change.

## Goal & scope

Decided levers (from brainstorming, 2026-07-05):

- **Goal:** build a real-code-sourced **eval slice** first (validate cheaply),
  expandable to train/dev later. No change to the coverage denominator or the
  existing splits in this phase.
- **Injection:** model-assisted **semantic** bugs via **Approach A —
  region-scoped localized edit** (the model edits a selected function/region,
  not the whole file). Model = **`gpt-5.4-mini` only** (no gpt-5.5 without
  explicit per-task permission).
- **Error shape:** accept **both** single-error and cascade instances; **tag
  cascade size** so analysis can slice fix-rate by cascade depth.
- **Steering:** **realistic any-family** — inject the most natural semantic bug
  for the region (wrong overload, type mismatch, undeclared name, missing
  member, const violation, …), *not* steered by the coverage gap list. For an
  eval set the point is difficulty/realism, not coverage.

**In scope:** the `gen/realcorpus/` module; a runnable that emits an eval-slice
JSONL in the `run_sweep` input format; tests. **Out of scope (future):**
regenerating train/dev from real code; history-anchored injection (Approach C);
multi-project corpora beyond LLVM.

## Architecture

New self-contained package `src/gen/realcorpus/` (follows the repo's
"each direction owns its lib + runnable + tests" convention). Real code in,
injected-error `Record`s out.

```
compile_commands.json (LLVM @ llvmorg-22.1.8)
  │ ① corpus.py     sample TUs; keep those that compile CLEAN under patched clang
  ▼
correct real TU
  │ ② region.py     pick a target function/span (brace-scan heuristic)
  ▼
  │ ③ inject.py     gpt-5.4-mini returns a MINIMAL edit (old→new) introducing a
  │   + prompt.py   realistic semantic bug in that region; apply → erroneous_src
  ▼
  │ ④ collect.py    verify erroneous_src with the real compile cmd; require a
  │                 primary diagnostic; count cascade; emit Record
  ▼
⑤ run_realcorpus.py  → eval-slice JSONL (run_sweep format)
  │
  ▼
⑥ (existing) run_sweep b0/b1/diag → aggregate_eval, sliced by cascade depth
```

### Components & interfaces

| unit | responsibility | key interface | reuses |
|---|---|---|---|
| `compile_db.py` (shared) | parse `compile_commands.json`; portable-ize a recorded command | `load_compile_db(path) -> {abs_file: entry}`; `build_clang_argv(entry, clang="__CLANG__", src="__SRC__") -> list[str]` | **extracted** from `real/reproduce_stage2_llvm.py` |
| `corpus.py` | sample candidate TUs; enforce correct-code invariant | `iter_clean_tus(db, verifier, *, limit, seed) -> Iterator[CleanTU]` where `CleanTU = (rel_path, src, compile_cmd)` | `FuzzlangClangVerifier` |
| `region.py` | choose a mutable span in a clean file | `select_regions(src, *, max_regions) -> list[Region]` (Region = char span of a function body) | pure text / brace scan |
| `prompt.py` | build the injection chat messages | `build_inject_prompt(region_text, file_head) -> list[msg]`; `parse_edit(reply) -> Edit|None` | — |
| `inject.py` | one model call → applied erroneous source | `inject_error(tu, region, chat) -> str|None` (returns erroneous_src or None) | `chat_backend` |
| `collect.py` | verify + emit | `collect_real_records(tu, erroneous_src, verifier) -> Record|None` (sets `cascade_size`) | `foundation.record`, verifier |
| `run_realcorpus.py` | CLI orchestration → JSONL | args below | `prepare_eval`-style row conversion |
| `tests/` | TDD with `MockVerifier` + mock chat | — | — |

**Why extract `compile_db.py`:** `_load_compile_db`, `_split_command`,
`_build_clang_argv` already exist inside `real/reproduce_stage2_llvm.py`. Both
`real/` and `gen/realcorpus/` need them; duplicating is a smell. Extract to a
shared module and have `reproduce_stage2_llvm.py` import from it (behavior
unchanged; covered by a characterization test). Proposed location:
`src/foundation/compile_db.py` (compile-command handling is shared substrate).

### Data flow & schema

Each emitted `foundation.record.Record`:

- `corrected_src` = the **real, clean** TU text.
- `erroneous_src` = the TU with the model's localized edit applied.
- `diagnostics = (primary DiagInfo,)` — first `error:` + `DiagID`, name via
  `diagtool`, as the verifier already produces.
- `provenance = Provenance(origin=Origin.GUIDED, source="llvm:<rel_path>",
  detail={"strategy": "realcorpus_inject", "region": <span>,
  "cascade_size": <int>, "edit": "<old→new summary>"})`.
  (Reusing `Origin.GUIDED`; a dedicated `Origin.REAL_INJECT` is a possible
  follow-up but not required — decide during planning.)
- `language` from the TU extension; `split = EVAL`.

The `run_realcorpus.py` CLI writes rows directly in the **`run_sweep` input
format** (`instance_id, buggy_src, corrected_src, compile_cmd, diag_id,
diag_name, language, cascade_size`) so metric #2 runs with no adapter. This
mirrors what `prepare_eval.py` produces for the toy-snippet eval.

### Injection prompt contract (Approach A)

- **Input to model:** the selected region text + a short file-head slice
  (includes / usings / nearby type context), plus the instruction to introduce
  **exactly one** realistic semantic error natural to this code, returning a
  **minimal edit** as `<<<OLD ... === NEW ... >>>` (unique old-snippet anchor).
- **Apply:** locate the unique `old` snippet in the full TU, replace with `new`.
  Reject if `old` is absent or non-unique (retry up to K).
- **Verify:** compile erroneous_src with the real cmd. Keep iff: original
  compiled clean (checked in ①) **and** erroneous errors with a parseable
  primary diagnostic. Record `cascade_size` = count of `error:` lines.
- **Budget:** small per call (region ≪ file). `gpt-5.4-mini`,
  `max_completion_tokens` via `build_chat_kwargs`.

### CLI (`run_realcorpus.py`)

```
PYTHONPATH=src python3 src/gen/realcorpus/run_realcorpus.py \
  --compile-db /p/lustre2/shan4/fuzzlang-llvm-build/compile_commands.json \
  --llvm-src   external/llvm-project \
  --clang-bin  $FUZZLANG_CLANG_BIN --diagtool-bin $FUZZLANG_DIAGTOOL_BIN \
  --model gpt-5.4-mini --base-url https://api.openai.com/v1 \
  --n-files 200 --regions-per-file 2 --retries 3 --workers 16 \
  --out data/gen/splits/eval_realcorpus.jsonl
```

## Compile environment & LLVM-version consistency

The **one-LLVM-version** hard rule (`llvmorg-22.1.8`) applies: the real-code
corpus, the compile commands, and the patched clang must all be 22.1.8. The
existing `compile_commands.json` at `/p/lustre2/shan4/fuzzlang-llvm-build/` may
be from LLVM `main` (the Stage-2 real work cloned `--branch main`). **Planning
must first verify** the DB's source root; if it is not the pinned tree,
**regenerate** `compile_commands.json` from `external/llvm-project` (ca7933e =
22.1.8) with `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON` (one-time ~30–60 min build on
a pdebug node; `clang` target must be built so generated `.inc` headers exist).

**Reproducibility caveat:** recorded commands carry machine-absolute `-I`
paths, so the eval JSONL is reproducible on *this* build tree, not portable.
Acceptable for our runs; note it in the dataset README.

## Testing (TDD, test-first)

- `compile_db.py`: parse a fixture DB; `build_clang_argv` drops `-o`, strips the
  recorded source path, forces `-fsyntax-only -fno-color-diagnostics`, appends
  `__SRC__`. Characterization test that `reproduce_stage2_llvm` output is
  unchanged after the extraction.
- `region.py`: brace-scan finds function spans; ignores strings/comments
  (reuse `mutate/_scan.py` masking).
- `prompt.py`: `parse_edit` reads the `<<<OLD/NEW>>>` shape; rejects
  missing/non-unique anchors.
- `collect.py`: with `MockVerifier`, a mutant that errors emits a `Record` with
  correct `cascade_size`; a mutant that still compiles emits nothing; a clean
  original is required.
- `inject.py`: with a mock chat returning a scripted edit, end-to-end produces
  erroneous_src; malformed replies retry then give up.

## Success criteria

1. **Builds:** `run_realcorpus.py` emits ≥ ~150 verified real-code eval
   instances with a non-trivial cascade-size distribution.
2. **Experiment:** re-run `b0/b1/diag` (matched budget, 3 seeds) on the slice;
   report fix-rate **sliced by cascade depth**. The design **succeeds as a
   research artifact whether or not** diag − b1 widens — a null result on
   real code is itself a finding. The pass bar for *this module* is: verified,
   reproducible, honestly-measured real-code instances.

## Risks & mitigations

| risk | mitigation |
|---|---|
| compile DB is `main`, not 22.1.8 | verify first; regenerate from pinned tree |
| model injects a *syntactic* not semantic bug | prompt asks for semantic; accept anyway (still valid), but tag family so we can measure the semantic fraction |
| model edit doesn't compile-error (no-op) or won't apply | retry K times; count and skip; report yield |
| large TUs slow to compile (~1–5 s each) | sample a few hundred files; `--workers`; `-fsyntax-only` |
| absolute `-I` paths non-portable | documented; eval runs on this tree |
| cost | region-scoped (small I/O), `gpt-5.4-mini`, capped `--n-files` |

## Out of scope / future

- Regenerate train/dev from real code (phase 2, if the eval slice shows signal).
- History-anchored injection (Approach C) using `real/` manifests.
- Non-LLVM corpora.
- A dedicated `Origin.REAL_INJECT` provenance value.
