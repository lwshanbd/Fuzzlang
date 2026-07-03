# Gen — dataset generation runs

Diagnostic coverage from the Gen direction (`src/gen/`), measured against the
catalog denominator (**3891** error diagnostics in `llvmorg-22.1.8`). Two stages
so far, each keeping only pairs the patched clang confirms (correct version
compiles clean, broken version triggers a real error diagnostic):

| Stage | Records | Distinct diagnostics | Coverage |
|---|---:|---:|---|
| Stage 1 — mechanical mutation | 832 | 59 | 59/3891 (1.5%) |
| Stage 1 + 2 (single-config guided) | 1454 | 577 | 577/3891 (14.8%) |
| Stage 1 + 2 (multi-config sweep) | 3448 | 963 | 963/3891 (24.7%) |
| Stage 1 + 2 (sweep + RUN-line cc1) | 5348 | 1185 | 1185/3891 (30.5%) |
| + catalog-driven (no example needed) | 10542 | 1742 | 1742/3891 (44.8%) |
| + feature/target-config verify (1 pass) | 12473 | 1921 | 1921/3891 (49.4%) |
| **+ feature-verify (2 passes)** | **14237** | **1977** | **1977/3891 (50.8%)** |

Stage 2 (compiler-guided LLM generation) is the breadth lever. Two mechanisms:
(a) mine Clang's own tests under a **sweep of language/standard configs** plus
each file's own **`%clang_cc1` RUN-line flags** (1391 distinct triggerable
diagnostics, from ~839 with one config); (b) **catalog-driven** generation for
the ~2700 diagnostics no test triggered — the LLM synthesizes a triggering
program from the diagnostic *name + message template* alone. (c) **feature/target
verification** (`--feature-verify`): 764 uncovered diagnostics are real code
errors gated behind a flag (OpenMP, ObjC-ARC, HLSL, OpenCL, modules, SVE/SME…);
the model already writes the feature code from the name, so verifying under those
configs (and hinting the prompt) keeps the pair. Together, across unioned passes,
they reach **50.8%** of all error diagnostics; `covered@target` (≥3 examples) is
**1580/3891 (40.6%)**.

**Code vs invocation diagnostics.** 402 of the 3891 error diagnostics
(Driver/Frontend/Serialization/InstallAPI/CrossTU/Refactoring) are
invocation/environment errors — the source is *correct* and only the command
line / build setup is wrong, so they can't be a broken-code/corrected-code pair
and are structurally uncoverable here. Measured against the **3489 code
diagnostics** (`run_coverage --code-only`), coverage is **1977/3489 = 56.7%**
(covered@target 45.3%). Every covered diagnostic is a code diagnostic.

# Stage 1 — mechanical mutation

## Corpus

`corpus/` — **36** small, self-contained, *correct* programs (20 `.cpp`, 16
`.c`), hand-written with **no `#include`** so they compile clean under
`clang -fsyntax-only` with no flags or include paths. All 36 verified clean
before generation (`collect.py` drops any source whose original does not
compile). Construct variety (classes, templates, inheritance, operator
overloading, lambdas, enums, switch, loops, ternaries, function pointers,
unions, bitfields, goto, …) is what spreads the mutations across diagnostics.

## Run

Patched clang/diagtool `llvmorg-22.1.8`; all four text/token mutations
(`delete_semicolon`, `delete_bracket`, `replace_colon_with_semicolon`,
`delete_comma`).

```bash
export FUZZLANG_CLANG_BIN=/path/to/fuzzlang-clang/bin/clang
export FUZZLANG_DIAGTOOL_BIN=/path/to/fuzzlang-clang/bin/diagtool

PYTHONPATH=src python3 src/gen/run_gen.py \
    --sources data/gen/corpus/*.c data/gen/corpus/*.cpp \
    --out data/gen/mechanical.jsonl

PYTHONPATH=src python3 src/coverage/run_coverage.py \
    --records data/gen/mechanical.jsonl --target 3 --gap-out data/gen/gaps.jsonl
```

`mechanical.jsonl` and `gaps.jsonl` are gitignored (`*.jsonl`); regenerate with
the commands above.

## Results

- **Records:** 832 (verified broken/corrected pairs) from 36 programs.
- **Coverage:** **59 / 3891 distinct error diagnostics (1.5%)**; **30** reach
  the multiplicity target (≥3 examples). 3861 diagnostics remain below target.

| Component | Covered / total |
|---|---|
| Sema | 31 / 2747 |
| Parse | 25 / 420 |
| Common | 3 / 85 |
| Driver, Lex, Frontend, AST, Serialization, InstallAPI, Refactoring, CrossTU | 0 |

## What mechanical mutation actually hits

Deleting/replacing single punctuation lands overwhelmingly on **Parse** and the
shared **Common** "expected X" family, plus a useful tail of **Sema** errors
once the broken token still parses into an ill-typed program. Top covered
diagnostics by example count:

| n | component | diagnostic |
|---:|---|---|
| 236 | Common | err_expected |
| 76 | Parse | err_expected_semi_after_stmt |
| 67 | Parse | err_invalid_token_after_toplevel_declarator |
| 55 | Parse | err_expected_semi_declaration |
| 40 | Sema | err_main_global_variable |
| 38 | Parse | err_expected_semi_after_expr |
| 37 | Common | err_expected_after |
| 33 | Parse | err_expected_semi_decl_list |
| 27 | Parse | err_expected_fn_body |
| 22 | Parse | err_function_definition_not_allowed |
| 21 | Sema | err_undeclared_var_use_suggest |

Sema reach (a sample of the 31): `err_typecheck_expression_not_modifiable_lvalue`,
`err_bound_member_function`, `err_unknown_typename`, `err_case_not_in_switch`,
`err_incomplete_base_class`, `err_lambda_impcap`,
`err_constexpr_var_requires_const_init`, `err_virtual_non_function`,
`err_auto_variable_cannot_appear_in_own_initializer`.

**Takeaway:** text-level mutation cheaply saturates the punctuation/parse
diagnostics but barely touches the 2747-diagnostic Sema space and nothing in
Lex/Driver/Frontend/AST. Closing those gaps is the job of Stage 2.

# Stage 2 — compiler-guided LLM generation

`src/gen/run_guided.py`: mine example snippets per diagnostic from Clang's own
regression tests (each run through the patched clang to label it), then prompt an
LLM for a *fresh* correct/broken program pair for each mined diagnostic and keep
it only if it verifies. Same correct-code invariant as Stage 1, enforced in
`gen/guided/generate.py`.

**Breadth comes from mining configs.** A single `-std=c++17` mining config
mismines most of `clang/test` — a C file even errors on the driver flag instead
of triggering its intended diagnostic — capping mined diagnostics near ~839. Two
config layers fix this:

1. **Language/standard sweep** (`sweep_configs()`: C89..C++2b, Objective-C/C++) —
   each file tried under every config, diagnostics unioned. → 1141 distinct.
2. **Per-file `%clang_cc1` RUN-line flags** (`runline.parse_cc1_configs`) — replay
   each test's own frontend flags (`-triple`, `-target-feature`, `-fopenmp`, MS
   extensions) as `clang -cc1 … -fsyntax-only`, reaching flag-gated diagnostics
   the language sweep can't. → **1391 distinct** (on `clang/test/OpenMP` alone,
   59 → 101, +71%).

Generation verifies each pair under the language sweep **plus the configs that
triggered that diagnostic**, so an OpenMP diagnostic is checked under `-fopenmp`.

## Run

Model **`gpt-5.4-mini`** via the OpenAI API; full `clang/test`, sweep + RUN-line
cc1, 48 mining threads. Breadth is grown by **unioning independent passes** —
each converts a different subset of the harder diagnostics:

```bash
PYTHONPATH=src python3 src/gen/run_guided.py \
    --tests external/llvm-project/clang/test --out data/gen/guided.jsonl \
    --model gpt-5.4-mini --base-url https://api.openai.com/v1 \
    --workers 48 --samples-per-diag 1
# repeat to guided2/3/4.jsonl (vary --samples-per-diag; --gaps to focus later
# passes on what's still uncovered), union+dedup by record_id into all.jsonl:
PYTHONPATH=src python3 src/coverage/run_coverage.py \
    --records data/gen/all.jsonl --target 3 --gap-out data/gen/gaps.jsonl
```

## Results (mining + catalog, unioned passes)

- **Mining:** **1391** distinct diagnostics from **21,359** test files (sweep +
  RUN-line cc1), vs ~839 single-config.
- **Catalog-driven:** for the ~2700 diagnostics no test triggered,
  `--catalog-targets` generates from name + message template alone (no example).
  On a random uncovered sample ~50% produce a verified pair; one full pass added
  **+339 distinct** diagnostics.
- **Combined coverage:** **1977 / 3891 (50.8%)** distinct across 10 unioned passes
  (**14,237** deduped records), up from 1185 (30.5% mining-only), 963 (24.7%),
  577 (14.8%), 59 (1.5% mechanical); **1580 (40.6%)** at multiplicity target ≥3.
  Generation is thread-parallel (`--gen-workers`); a full catalog pass runs in
  minutes.

| Component | Stage 1 | + sweep | + catalog | + feature-verify |
|---|---:|---:|---:|---:|
| Sema | 31 / 2747 | 758 | 1372 | **1568 / 2747 (57%)** |
| Parse | 25 / 420 | 130 | 230 | **261 / 420 (62%)** |
| Lex | 0 / 191 | 53 | 106 | **111 / 191 (58%)** |
| Common | 3 / 85 | 19 | 26 | 29 / 85 |
| AST | 0 / 46 | 3 | 6 | 7 / 46 |
| Driver / Frontend / Serialization / InstallAPI / Refactoring / CrossTU | 0 | 0 | 0 | 0 |

The RUN-line pass uniquely reached **159 diagnostics** the language sweep can't
(OpenMP `err_omp_*` and other flag-gated); catalog-driven generation then added
the never-triggered tail.

**Takeaway & remaining gaps.** Guided generation now covers ~40% of all error
diagnostics, concentrated in Sema/Parse/Lex/AST. The remaining gaps are
structural: **Driver/Frontend/Serialization/InstallAPI** (0%) need real
multi-file / driver-level compiler *invocations*, not single-TU `-fsyntax-only`
snippets; and the residual Sema/Parse tail is diagnostics needing specific
targets/flags or contexts the LLM can't synthesize hermetically. More
independent catalog passes still convert new diagnostics (diminishing). The
refined `data/gen/gaps.jsonl` (2948 below target) drives the next round.

# Dataset assembly (dedup + splits)

`src/gen/run_dataset.py` turns the unioned records into a usable dataset:

- **Dedup** (`dedup_records`): drop cosmetic duplicates — records sharing a
  diagnostic and a whitespace-normalized 5-line window around the error line —
  keeping genuinely distinct programs so multiplicity stays honest.
- **Splits** (`split_records`): train/dev/eval, **isolated by
  `provenance.source`** (deterministic salted hash; all records of one source
  land in one split, so no program's variants leak across splits).

```bash
PYTHONPATH=src python3 src/gen/run_dataset.py \
    --records data/gen/all.jsonl --out-dir data/gen/splits \
    --salt fuzzlang-gen-v1 --dev-fraction 0.1 --eval-fraction 0.1
```

Result (`data/gen/splits/manifest.json`): **14,237 → 13,519 records after dedup**
(718 removed); train 10,682 / dev 1,448 / eval 1,389; provenance isolation OK.
Because isolation is by source (not diagnostic), a diagnostic can recur across
splits via different sources: **63% of eval diagnostics also appear in train**
(held-out instances of seen diagnostics) and 141 are eval-only (a
generalization tail). The split JSONLs and `manifest.json` are gitignored data
artifacts (regenerate with the command above); the numbers here are the record.
