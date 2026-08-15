from __future__ import annotations

from gen.fuzzlang_dsl.code_witness import (
    CodeWitnessRequest,
    build_code_append_messages,
)


def _request() -> CodeWitnessRequest:
    return CodeWitnessRequest(
        diag_name="err_omp_no_clause_for_directive",
        diag_id=None,
        diag_message="expected an OpenMP clause",
        language="c++",
        tablegen_definition='def err_omp_no_clause_for_directive : Error<"expected an OpenMP clause">;',
        source_id="source",
        source_path="llvm/lib/Support/example.cpp",
        project="llvm",
        compile_cmd=("__CLANG__", "-std=c++23", "-fopenmp", "__SRC__"),
        corrected_src="int value;\n",
        window_start=0,
        window_end=10,
    )


def test_append_prompt_allows_directive_only_when_explicitly_enabled():
    ordinary = build_code_append_messages(_request())
    directive = build_code_append_messages(
        _request(), allow_preprocessor_directives=True,
    )

    assert "not a preprocessor directive" in ordinary[0]["content"]
    assert "may use a bounded preprocessor directive" in directive[0]["content"]
