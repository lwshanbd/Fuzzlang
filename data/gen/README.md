# Gen — dataset generation runs

Diagnostic coverage from the Gen direction (`src/gen/`), measured against the
catalog denominator (**3891** error diagnostics in `llvmorg-22.1.8`). Two stages
so far, each keeping only pairs the patched clang confirms (correct version
compiles clean, broken version triggers a real error diagnostic):

| Stage | Records | Distinct diagnostics | Coverage |
|---|---:|---:|---|
| Stage 1 — mechanical mutation | 832 | 59 | 59/3891 (1.5%) |
| Stage 1 + 2 (single-config guided) | 1454 | 577 | 577/3891 (14.8%) |
| **Stage 1 + 2 (multi-config sweep guided)** | **3448** | **963** | **963/3891 (24.7%)** |

Stage 2 (compiler-guided LLM generation) is the breadth lever: mining Clang's
own tests under a **sweep of language/standard configs** exposes many more
distinct diagnostics, and the LLM turns each into a verified pair — reaching Sema,
Lex and AST diagnostics that punctuation mutation structurally cannot.

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

**Breadth comes from the multi-config sweep.** A single `-std=c++17` mining
config mismines most of `clang/test` — a C file even errors on the driver flag
instead of triggering its intended diagnostic — capping mined diagnostics near
~839. Mining each file under a sweep of language/standard configs
(`sweep_configs()`: C89..C++2b, Objective-C/C++) and unioning the diagnostics
each triggers exposes far more distinct kinds (**1141** from the full tree).
Generation verifies each pair under the same sweep, so C/Objective-C diagnostics
are checked under the right language.

## Run

Model **`gpt-5.4-mini`** via the OpenAI API; full `clang/test` tree, 9-config
sweep, 32 mining threads. Two independent generation passes (one at
`--samples-per-diag 1`, one at `2`) unioned — independent passes convert
different subsets of the harder diagnostics, so the union grows breadth.

```bash
PYTHONPATH=src python3 src/gen/run_guided.py \
    --tests external/llvm-project/clang/test --out data/gen/guided.jsonl \
    --model gpt-5.4-mini --base-url https://api.openai.com/v1 \
    --workers 32 --samples-per-diag 1
# second pass -> data/gen/guided2.jsonl (--samples-per-diag 2), then union+dedup
# by record_id into data/gen/all.jsonl and measure:
PYTHONPATH=src python3 src/coverage/run_coverage.py \
    --records data/gen/all.jsonl --target 3 --gap-out data/gen/gaps.jsonl
```

## Results

- **Mining:** **1141** distinct diagnostics from **21,359** test files under the
  9-config sweep (vs ~839 single-config) — mining is no longer the bottleneck.
- **Generation:** a pair attempted for every mined diagnostic; ~76% of targets
  per pass yield a verified pair. Two unioned passes → **3448** deduped records.
- **Combined coverage:** **963 / 3891 (24.7%)** distinct, up from 577 (14.8%
  single-config) and 59 (1.5% mechanical); **500 (12.9%)** now at multiplicity
  target ≥3.

| Component | Stage 1 | + guided (single-config) | + guided (sweep) |
|---|---:|---:|---:|
| Sema | 31 / 2747 | 440 | **758 / 2747 (28%)** |
| Parse | 25 / 420 | 82 | **130 / 420 (31%)** |
| Lex | 0 / 191 | 42 | **53 / 191 (28%)** |
| Common | 3 / 85 | 12 | 19 / 85 |
| AST | 0 / 46 | 1 | 3 / 46 |
| Driver / Frontend / Serialization / InstallAPI / Refactoring / CrossTU | 0 | 0 | 0 |

Guided generation reached **904 diagnostics mechanical mutation never did**.

**Takeaway & remaining gaps.** Guided sweep generation covers the Sema/Parse/Lex
space broadly. Two structural gaps remain: (1) **Driver/Frontend/Serialization**
(0%) need real multi-file compiler *invocations*, not single-TU `-fsyntax-only`
snippets; (2) the mining ceiling under these driver configs is ~1141 — breaking
past it means mining Clang's `%clang_cc1` RUN-line flags (`-triple`,
`-target-feature`, `-fopenmp` — the openmp/target-feature tests alone are tens of
thousands of files that our language-only sweep never triggers). Those are the
next breadth tiers, driven by the refined `data/gen/gaps.jsonl`.
