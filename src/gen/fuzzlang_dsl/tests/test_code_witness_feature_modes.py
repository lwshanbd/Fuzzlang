from __future__ import annotations

from gen.fuzzlang_dsl.code_witness import CodeWitnessRequest
from gen.fuzzlang_dsl.run_local_code_witness import _supports_request_compile_mode


def _request(diag_name: str, *compile_flags: str) -> CodeWitnessRequest:
    return CodeWitnessRequest(
        diag_name=diag_name,
        diag_id=None,
        diag_message="test diagnostic",
        language="c++",
        tablegen_definition=f'def {diag_name} : Error<"test diagnostic">;',
        source_id="source",
        source_path="llvm/lib/Support/example.cpp",
        project="llvm",
        compile_cmd=("__CLANG__", *compile_flags, "__SRC__"),
        corrected_src="int value;\n",
        window_start=0,
        window_end=10,
    )


def test_feature_mode_gate_accepts_openmp_and_blocks_compile_commands():
    openmp = _request(
        "err_omp_no_clause_for_directive", "-std=c++23", "-fopenmp",
    )
    blocks = _request(
        "err_capture_block_variable", "-std=c++23", "-fblocks",
    )

    assert _supports_request_compile_mode(openmp)
    assert _supports_request_compile_mode(blocks)


def test_feature_mode_gate_accepts_cpp2c_compile_commands():
    cpp2c = _request(
        "err_static_lambda_captures", "-std=c++2c", "-fsyntax-only",
    )

    assert _supports_request_compile_mode(cpp2c)


def test_feature_mode_gate_accepts_test_evidenced_compiler_profile():
    no_gnu_inline_asm = _request(
        "err_gnu_inline_asm_disabled", "-std=c++17", "-fno-gnu-inline-asm",
    )

    assert _supports_request_compile_mode(no_gnu_inline_asm)


def test_feature_mode_gate_accepts_sycl_profile():
    sycl = _request(
        "warn_sycl_kernel_name_not_a_class_type", "-std=c++23", "-Xclang", "-fsycl-is-device",
    )

    assert _supports_request_compile_mode(sycl)


def test_feature_mode_gate_allows_explicit_preprocessor_witness_only():
    preprocessor = CodeWitnessRequest(**{
        **_request("err_pp_invalid_directive", "-std=c++23").to_dict(),
        "feature_mode": "preprocessor",
    })

    assert not _supports_request_compile_mode(preprocessor)
    assert _supports_request_compile_mode(
        preprocessor, allow_preprocessor_directives=True,
    )
