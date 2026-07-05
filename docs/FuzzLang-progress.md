# FuzzLang: implementation progress and results

Status report on the implementation against `FuzzLang-Proposal.md`. Companion to
that document — the proposal is the plan, this is what exists and what the
numbers are. Data-level detail for the Gen results lives in `data/gen/README.md`.

**One-line status.** Foundation and Coverage are built and tested; Gen (all three
strategies) is built, tested, and *run at scale*, producing a verified,
deduplicated, provenance-split dataset that covers **79.5% of in-scope C/C++
error diagnostics**. Real and Repair are reused scaffolds, not yet run this cycle.

Everything below is reproducible from the committed code; the LLVM version is
pinned to `llvmorg-22.1.8` everywhere. Test suite: **175 passing**.

---

## 1. Success-criteria scorecard

The proposal (§3) judges the project by three numbers, in priority order:

| # | Criterion | Status | Result |
|---|---|---|---|
| 1 | **Diagnostic coverage** (headline) | **done, driven up** | **1538 / 1935 in-scope C/C++ error diagnostics = 79.5%**; 61.7% at multiplicity ≥3 |
| 2 | **Verified repair rate** | not run this cycle | repair scaffold (loop, baselines `b0`–`b3`, `diag` method, metrics) reused as-is; dataset now exists to run it |
| 3 | **Real-world generalization** | not run this cycle | Real miners (`real/`) reused; Stage-1 manifests present; not reproduced this cycle |

Criterion 1 — the headline — is the focus of this cycle and is done. Criteria 2
and 3 are unblocked (the dataset and splits they need now exist) but not yet
executed.

### The coverage number, at three honesty levels

The denominator is the **3891** error diagnostics declared in Clang's TableGen at
`llvmorg-22.1.8` (Foundation catalog). Not all of those are single-file C/C++
code errors, so we report against progressively more principled denominators:

| Denominator | Covered | % |
|---|---:|---:|
| all error diagnostics (3891) | 2432 | 62.5% |
| code diagnostics — excl. invocation/env (3489) | 2432 | 69.7% |
| **strict C/C++ code — excl. dialect/target (1935)** | **1538** | **79.5%** |

The strict number is the honest headline: it excludes (a) **invocation/
environment** diagnostics (Driver/Frontend/Serialization/InstallAPI/CrossTU/
Refactoring) where the *source* is correct and only the command line is wrong —
structurally impossible as a broken-code/corrected-code pair — and (b)
**non-C/C++ dialect/target** diagnostics (Objective-C, OpenMP, OpenACC, OpenCL,
CUDA/HIP, SYCL, HLSL, Microsoft-only, and CPU-target intrinsics). Their being
uncovered is expected and correct, not a dataset weakness.

Per component (strict): **Sema 82%, Parse 86%, Lex 62%**.

---

## 2. Foundation — built and in use

The shared substrate the proposal calls for (§4 Foundation) is in place.

- **Patched Clang at `llvmorg-22.1.8`.** The gating dependency. The
  `TextDiagnosticPrinter` patch (`src/foundation/patches/`) was rebased from
  19.1.7 across three major versions (the `DiagOpts` pointer→reference change)
  and built; the binary emits `DiagID: N` on stderr so the verifier reads the
  diagnostic identifier directly instead of string-matching localized messages.
  Installed at `/p/lustre2/shan4/fuzzlang-clang/bin/{clang,diagtool}`.
- **Diagnostic catalog** (`foundation/diagnostics/catalog.py`): parses the `.td`
  files → **3891** error diagnostics (name, severity, message template,
  component). This is the coverage denominator.
- **Verifier** (`foundation/verifier/`): `FuzzlangClangVerifier` compiles a source
  and returns a typed `VerifierResult` (ok / primary `DiagInfo` with id, name,
  location); `MockVerifier` for tests; `StockClangVerifier` fallback. Hardened to
  decode non-UTF-8 compiler stderr.
- **Record schema** (`foundation/record.py`): the (`erroneous_src`,
  `corrected_src`, `diagnostics`, `provenance`, `split`) unit; the correct-code
  invariant (every core record carries `corrected_src`) is enforced in the schema.
- **Dedup** (`foundation/ast_hash.py`): whitespace/AST-normalized window hashing,
  used by dataset assembly.

---

## 3. Coverage — the metric, and the scope filter

`coverage/` implements the headline metric and the gap list that drives Gen
(proposal §4 Coverage). `tracker.build_report` counts records against the
catalog → covered/total, multiplicity, per-component breakdown, and the gap list.

Two principled denominator filters were added this cycle, answering the
proposal's open question "what diagnostic space do we claim?":

- `--code-only`: drop invocation/environment components.
- `--exclude-names <file>`: drop an explicit list of diagnostics — used for the
  scope filter below.

### Scope classification (strict C/C++)

`gen/scope.py` + `gen/run_scope.py` classify every catalog diagnostic as strict
C/C++ (in scope) or a non-C/C++ dialect/target (out of scope), by:

1. high-precision **vendor keywords** (omp, acc, objc, opencl, cuda, hlsl, sycl,
   declspec, sve/sme/neon/riscv/…) → 1080 out;
2. an **LLM judge** (`gpt-5.4-mini`, batched) over the rest → 767 more out;
3. an **audit by six Claude sub-agents** over all 767 LLM verdicts, which found
   and corrected **58 false positives** (the weaker model had wrongly excluded
   core standard diagnostics — e.g. `err_typecheck_call_too_few/many_args*`,
   GNU vector extensions, atomic builtins, `_Generic`, `#embed`).

Result: **1789 of 3891 diagnostics are out of scope**; the strict C/C++ code
denominator is **1935**. The list is committed at `data/gen/out_of_scope.txt`
(auditable and editable).

---

## 4. Gen — built, tested, run at scale (the bulk of this cycle)

All three generation strategies from the proposal (§4 Gen) are implemented,
unit-tested, and executed. Every record is verifier-checked: kept only if the
correct version compiles and the broken version triggers a real error
diagnostic. Origin/strategy is recorded on each record.

### 4.1 Mechanical mutation (`gen/mutate/`, `gen/collect.py`)

Text/token transforms on correct code — delete a semicolon, delete one half of a
matched bracket pair, `:`→`;`, delete a comma — with a code-aware scanner that
ignores comments and string/char literals. A registry lists them; AST-based
mutations sit behind a libclang guard. `collect.py` applies the correct-code
invariant. **832 records, 59 distinct diagnostics (1.5%)** — cheap breadth on the
punctuation/parse family, as expected; it barely touches Sema.

### 4.2 Guided generation from compiler evidence (`gen/guided/`, `gen/run_guided.py`)

The primary new engine. Mine example snippets per diagnostic from Clang's own
`clang/test` (run each through the patched clang to label it), then prompt an LLM
for a *fresh* correct/broken pair for each target diagnostic and keep it only if
it verifies. This is where coverage was driven up, through a sequence of levers
(cumulative distinct-diagnostic coverage):

| Lever | Coverage (of 3891) | What it fixed |
|---|---:|---|
| single-config guided | 14.8% | baseline; `-std=c++17` mismined C files |
| multi-config **sweep** | 24.7% | mine each file under 9 language/std configs, union |
| **RUN-line `%clang_cc1`** flags | 30.5% | replay each test's own `-triple`/`-fopenmp`/… → flag-gated diagnostics |
| **catalog-driven** (no example) | 44.8% | generate the ~2700 never-mined diagnostics from name+message alone |
| **feature-verify** configs | 50.8% | verify pairs under `-fopenmp`/`-fobjc-arc`/… (the model already wrote the feature code) |
| expanded features + **gpt-5.5** tail | 62.5% | stronger model reproduces template/attribute/builtin errors 5.4-mini could not |

Engineering notes: generation is thread-parallel (`--gen-workers`; a full catalog
pass runs in minutes rather than hours); `--skip-mining` for catalog-only passes;
breadth is grown by **unioning independent passes** (temperature diversity
converts different subsets). Models: `gpt-5.4-mini` by default, `gpt-5.5` for the
hard tail.

### 4.3 Model-assisted mutation

Realized as the catalog-driven and gpt-5.5 modes above: for diagnostics rule-based
mutation and mining can't reach, the model synthesizes a triggering program from
the diagnostic's name and message template, verified before it enters the dataset.

### 4.4 The Coverage⟷Gen loop

Closed and exercised repeatedly: Coverage emits the gap list → Gen targets it →
Coverage re-measures. The gap list is filtered to in-scope uncovered diagnostics
to focus model budget.

---

## 5. The dataset (`gen/dataset.py`, `gen/run_dataset.py`)

The verified records are assembled into a usable dataset:

- **Dedup**: drop cosmetic duplicates (same diagnostic + whitespace-normalized
  5-line window), keeping genuinely distinct programs so multiplicity is honest.
- **Splits**: train/dev/eval, **isolated by provenance source** (deterministic
  salted hash — all records of one source stay in one split, no leakage), mirroring
  `real/split_llvm_train_dev.py`.

Strict-C/C++ dataset: **14,483 records → 13,745 after dedup**, split **train
10,973 / dev 1,402 / eval 1,370** (provenance isolation verified). Because
isolation is by source, a diagnostic can recur across splits via different
sources: **68% of eval diagnostics also appear in train** (held-out instances of
seen diagnostics — the primary repair-eval regime), with 96 eval-only
(generalization tail). Split JSONLs and the manifest are gitignored artifacts,
regenerable from `data/gen/all.jsonl`.

---

## 6. Real and Repair — reused, not yet run

- **Real** (`real/`): Stage-1 harvest, LLVM Stage-2 reproduction, provenance-
  isolated LLVM split, and a GitHub compile-error miner are present with Stage-1
  manifests for 8 projects. Not reproduced this cycle. Provides criterion 3.
- **Repair** (`repair/`): the repair loop (`run_repair_loop`), baseline ladder
  `b0`–`b3`, the diagnostic-aware `diag` method, ablations, and eval metrics
  (verified-fix-rate with bootstrap CI) are reused as-is. The `OpenAIChatBackend`
  was fixed to support gpt-5/o-series token params. Not run this cycle; the
  dataset and splits it needs now exist. Provides criterion 2.

---

## 7. Reproducibility

- One LLVM version everywhere: `llvmorg-22.1.8`. Patched clang built via
  `src/foundation/build_fuzzlang_clang.sh`.
- Tests: `python3 -m pytest -q` (175 passing). Set `FUZZLANG_CLANG_BIN` /
  `FUZZLANG_DIAGTOOL_BIN` to run the compiler-backed integration tests.
- Full generation + coverage + dataset commands are in `data/gen/README.md`.
- LLM: OpenAI-compatible endpoint; `gpt-5.4-mini` default, `gpt-5.5` for the hard
  tail. Key kept out of the repo.
- Compute: mining/generation run via `srun` on the cluster's `pdebug` partition;
  generation is API-bound and thread-parallel.

---

## 8. Honest limitations and open items

- **The uncovered ~397 in-scope diagnostics** are the hard residual: multi-file
  errors (e.g. C++20 module ODR violations, which need ≥2 modules) and very
  specific rare constructs. They are near the ceiling for single-file generation;
  a multi-file/module generation mode would be needed to reach them.
- **Multiplicity**: 61.7% of covered in-scope diagnostics reach the ≥3 target;
  the rest are covered with 1–2 examples. Raising multiplicity is a separate
  (depth) axis from breadth.
- **Scope classification** is LLM-assisted and audited but not infallible; the
  committed `out_of_scope.txt` is the reviewable record and can be hand-edited.
- **Criteria 2 and 3 are unrun.** The immediate next step is to wire the dataset
  splits into the repair loop for a first verified-fix-rate, and to reproduce a
  slice of the Real evaluation column.

---

## 9. Next steps

1. **Repair eval (criterion 2):** run `b0`–`b3` + `diag` on the dev/eval splits;
   report verified-fix-rate with CIs and by diagnostic family.
2. **Real (criterion 3):** reproduce a Real evaluation slice and measure repair
   generalization on it.
3. **Depth:** raise multiplicity toward ≥3 on the covered in-scope tail.
4. **Optional breadth:** a multi-file/module generation mode for the ODR residual.
