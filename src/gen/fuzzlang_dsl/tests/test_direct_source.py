from __future__ import annotations

from gen.fuzzlang_dsl.code_witness import CodeWitnessRequest
from gen.fuzzlang_dsl.direct_source import replay_direct_injector_on_source
from gen.fuzzlang_dsl.injector import FuzzLangInjector
from foundation.types import DiagInfo, VerifierResult


def _request() -> CodeWitnessRequest:
    source = "int f(){ int x = 0; return x; }\n"
    return CodeWitnessRequest(
        diag_name="err_target", diag_id=17, diag_message="target error",
        language="c++", tablegen_definition="def err_target : Error<\"x\">;",
        source_id="llvm@abc:lib/a.cpp", source_path="lib/a.cpp",
        project="llvm", compile_cmd=("__CLANG__", "-fsyntax-only", "__SRC__"),
        corrected_src=source, window_start=0, window_end=len(source),
    )


def _injector() -> FuzzLangInjector:
    return FuzzLangInjector(
        target_diag="err_target", target_diag_id=17, language="c++",
        operation="insert", old_patterns=(), new_text="&",
        left_context=("return",), right_context=("<ID0>", ";"),
        portable=True, replacement_parts=(("literal", "&"),),
    )


class _Verifier:
    def verify(self, source, _command, *, logical_path):
        if "&" not in source:
            return VerifierResult(True, None, "")
        return VerifierResult(False, DiagInfo(
            diag_id=17, diag_name="err_target", diag_msg="target error",
            file=logical_path, line=1, col=1, start_byte=0, end_byte=1,
            span_snippet="&",
        ), "typed error")


def test_direct_injector_requires_exact_typed_seed_replay():
    result = replay_direct_injector_on_source(_injector(), _request(), _Verifier())

    assert result is not None
    assert result.diagnostics[0].diag_name == "err_target"
    assert result.corrected_src == _request().corrected_src
    assert result.provenance.detail["strategy"] == "gemma_direct_fuzzlang_injector"
    assert result.provenance.detail["injector_replay_exact"] is True


def test_direct_injector_rejects_wrong_typed_diagnostic():
    class _WrongVerifier(_Verifier):
        def verify(self, source, command, *, logical_path):
            result = super().verify(source, command, logical_path=logical_path)
            if result.diag is None:
                return result
            return VerifierResult(False, DiagInfo(
                diag_id=18, diag_name="err_other", diag_msg="other error",
                file=logical_path, line=1, col=1, start_byte=0, end_byte=1,
                span_snippet="&",
            ), "typed error")

    assert replay_direct_injector_on_source(
        _injector(), _request(), _WrongVerifier(),
    ) is None
