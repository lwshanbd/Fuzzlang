# Gen — dataset generation runs

Diagnostic coverage from the Gen direction (`src/gen/`), measured against the
catalog denominator (**3891** error diagnostics in `llvmorg-22.1.8`). Two stages
so far, each keeping only pairs the patched clang confirms (correct version
compiles clean, broken version triggers a real error diagnostic):

| Stage | Records | Distinct diagnostics | Coverage |
|---|---:|---:|---|
| Stage 1 — mechanical mutation | 832 | 59 | 59/3891 (1.5%) |
| **Stage 1 + 2 (mechanical + guided)** | **1454** | **577** | **577/3891 (14.8%)** |

Stage 2 (compiler-guided LLM generation) lifts coverage ~10× and reaches Sema,
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
regression tests (each run through the patched clang to label it), then for each
diagnostic still below target in `gaps.jsonl`, prompt an LLM for a *fresh*
correct/broken program pair and keep it only if it verifies. Same correct-code
invariant as Stage 1, enforced in `gen/guided/generate.py`.

## Run

Model **`gpt-5.4-mini`** via the OpenAI API; mined the full `clang/test` tree.

```bash
PYTHONPATH=src python3 src/gen/run_guided.py \
    --tests external/llvm-project/clang/test --gaps data/gen/gaps.jsonl \
    --out data/gen/guided.jsonl \
    --model gpt-5.4-mini --base-url https://api.openai.com/v1
cat data/gen/mechanical.jsonl data/gen/guided.jsonl > data/gen/all.jsonl
PYTHONPATH=src python3 src/coverage/run_coverage.py \
    --records data/gen/all.jsonl --target 3 --gap-out data/gen/gaps.jsonl
```

## Results

- **Mining:** examples for **839** distinct diagnostics from **21,359** test
  files (that many yielded a named diagnostic under the default
  `-fsyntax-only -std=c++17`; files needing specific RUN-line flags are
  mishandled but still often trigger *a* diagnostic — fine for mining).
- **Generation:** 807 gap diagnostics targeted → **622 verified records
  (77%)**. Of those, **495 (80%) hit the exact target diagnostic**; the other
  127 hit a *different* real diagnostic (kept, since `--target-required` was
  dropped for the scale-up).
- **Combined coverage:** **577 / 3891 (14.8%)**, up from 59 (1.5%); 48 at
  multiplicity target ≥3.

| Component | Stage 1 | Stage 1 + 2 |
|---|---:|---:|
| Sema | 31 / 2747 | **440 / 2747 (16%)** |
| Parse | 25 / 420 | 82 / 420 (20%) |
| Lex | 0 / 191 | **42 / 191 (22%)** |
| Common | 3 / 85 | 12 / 85 |
| AST | 0 / 46 | 1 / 46 |
| Driver / Frontend / Serialization / InstallAPI / Refactoring / CrossTU | 0 | 0 |

Guided generation reached **518 diagnostics mechanical mutation never did**
(Sema 409, Parse 57, Lex 42, Common 9, AST 1) — e.g. access-control errors
(`err_access_ctor`, `err_access_friend_function`), `err_abstract_type_in_decl`,
`err__Pragma_malformed`, static-assert and constexpr failures.

**Takeaway:** guided LLM generation is the lever for the huge Sema space and for
Lex; the remaining gaps are Driver/Frontend/Serialization (which need real
compiler *invocations* / multi-file setups, not single-TU snippets) and the long
multiplicity tail (most covered diagnostics still have <3 examples). The refined
`data/gen/gaps.jsonl` (3843 below target) drives the next round.
