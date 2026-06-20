# Gen — mechanical mutation: first end-to-end run

First non-zero diagnostic coverage from the Gen direction (`src/gen/`): take
correct C/C++ programs, mechanically introduce errors, keep only the mutants the
patched clang confirms as real error diagnostics, and measure coverage against
the catalog denominator (**3891** error diagnostics in `llvmorg-22.1.8`).

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
Lex/Driver/Frontend/AST. Closing those gaps is the job of the next Gen stages
(compiler-evidence-guided and model-assisted mutation), driven by
`data/gen/gaps.jsonl`.
