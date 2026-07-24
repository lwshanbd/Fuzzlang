from __future__ import annotations

from foundation.record import Origin, Provenance, Record, Split
from foundation.types import DiagInfo
from foundation.verifier.base import VerifierResult
from gen.fuzzlang_dsl.injector import apply_injector
from gen.fuzzlang_dsl.undistillable_recovery import (
    recover_comment_replacement,
)


def _diagnostic() -> DiagInfo:
    return DiagInfo(
        diag_id=5200,
        diag_name="err_template_param_pack_must_be_last_template_parameter",
        diag_msg="target",
        file="llvm/lib/A.cpp",
        line=3,
        col=1,
        start_byte=0,
        end_byte=1,
        span_snippet="template",
    )


def test_comment_replacement_is_recovered_as_verified_portable_insertion():
    corrected = (
        "namespace sample {\n"
        "int value;\n"
        "/// Documentation that must remain in the correct source.\n"
        "struct Item {};\n"
        "}\n"
    )
    erroneous = corrected.replace(
        "/// Documentation that must remain in the correct source.",
        "template <typename... T, typename U> struct Error {};",
    )
    record = Record(
        record_id="undistillable-1",
        erroneous_src=erroneous,
        corrected_src=corrected,
        diagnostics=(_diagnostic(),),
        provenance=Provenance(
            Origin.MUTATE,
            "llvm:llvm/lib/A.cpp",
            detail={
                "compile_cmd": ["__CLANG__", "-fsyntax-only", "__SRC__"],
                "source_path": "llvm/lib/A.cpp",
            },
        ),
        split=Split.TRAIN,
    )

    class _Verifier:
        def verify(self, source, compile_cmd, *, logical_path):
            if "typename..." not in source:
                return VerifierResult(True, None, "")
            return VerifierResult(False, _diagnostic(), "")

    recovery = recover_comment_replacement(record, _Verifier())

    assert recovery is not None
    assert recovery.record.corrected_src == corrected
    assert recovery.record.erroneous_src != erroneous
    assert recovery.record.primary_diagnostic == _diagnostic()
    assert recovery.injectors
    assert all(injector.portable for injector in recovery.injectors)
    assert any(
        application.src == recovery.record.erroneous_src
        for injector in recovery.injectors
        for application in apply_injector(corrected, injector)
    )

