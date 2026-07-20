from __future__ import annotations

from foundation.record import Origin, Split
from foundation.types import DiagInfo, VerifierResult
from foundation.verifier.mock import MockVerifier, ok_result
from gen.realcorpus.finalize import (
    build_corrected_source_index,
    canonicalize_row,
    portable_source_path,
    to_repair_row,
)


def _diag(name: str = "err_expected_semi") -> DiagInfo:
    return DiagInfo(
        diag_id=123,
        diag_name=name,
        diag_msg="expected ';'",
        file="ignored.cpp",
        line=1,
        col=8,
        start_byte=0,
        end_byte=8,
        span_snippet="int x = 1",
    )


def _row(**updates) -> dict:
    row = {
        "instance_id": "realinject-1",
        "buggy_src": "int x = 1\n",
        "corrected_src": "int x = 1;\n",
        "compile_cmd": ["__CLANG__", "-fsyntax-only", "__SRC__"],
        "diag_id": 123,
        "diag_name": "err_expected_semi",
        "language": "c++",
        "cascade_size": 1,
        "target_diag": "err_expected_semi",
        "primary_matches_target": True,
        "project": "llvm",
        "source_path": (
            "/work/external/llvm-project/clang/lib/Sema/SemaThing.cpp"
        ),
        "region": [0, 10],
        "region_type": "function",
    }
    row.update(updates)
    return row


def test_canonicalize_revalidates_pair_and_preserves_generation_metadata():
    verifier = MockVerifier(
        lambda src, cmd, logical: (
            ok_result() if src.endswith(";\n") else
            VerifierResult(False, _diag(), "x:1:8: error: expected ';'\n")
        )
    )

    result = canonicalize_row(_row(), verifier, source_index={})

    assert result.status == "accepted"
    assert result.record is not None
    rec = result.record
    assert rec.provenance.origin is Origin.LLM
    assert rec.provenance.source == "llvm:clang/lib/Sema/SemaThing.cpp"
    assert rec.split is Split.EVAL
    assert rec.primary_diagnostic.diag_name == "err_expected_semi"
    assert rec.primary_diagnostic.file == "clang/lib/Sema/SemaThing.cpp"
    assert rec.provenance.detail["generation_label"] == "exact_target"
    assert rec.provenance.detail["compile_cmd"] == _row()["compile_cmd"]
    assert [call[0] for call in verifier.call_log] == [
        "int x = 1;\n", "int x = 1\n"
    ]


def test_canonicalize_rejects_noncompiling_corrected_source():
    verifier = MockVerifier(
        lambda src, cmd, logical: VerifierResult(False, _diag(), "error")
    )
    result = canonicalize_row(_row(), verifier, source_index={})
    assert result.status == "corrected_not_clean"
    assert result.record is None


def test_canonicalize_rejects_diagnostic_drift():
    verifier = MockVerifier(
        lambda src, cmd, logical: (
            ok_result() if src.endswith(";\n") else
            VerifierResult(False, _diag("err_other"), "error")
        )
    )
    result = canonicalize_row(_row(), verifier, source_index={})
    assert result.status == "diagnostic_drift"
    assert result.record is None


def test_missing_source_path_is_resolved_from_corrected_source(tmp_path):
    source = tmp_path / "external/llvm-project/llvm/lib/IR/Thing.cpp"
    source.parent.mkdir(parents=True)
    source.write_text("int x = 1;\n")
    index = build_corrected_source_index([str(source)])
    verifier = MockVerifier(
        lambda src, cmd, logical: (
            ok_result() if src.endswith(";\n") else
            VerifierResult(False, _diag(), "x:1:8: error: expected ';'\n")
        )
    )

    result = canonicalize_row(
        _row(source_path=None), verifier, source_index=index
    )

    assert result.status == "accepted"
    assert result.record.provenance.source == "llvm:llvm/lib/IR/Thing.cpp"


def test_test_source_is_rejected_before_compilation():
    verifier = MockVerifier(lambda src, cmd, logical: ok_result())
    result = canonicalize_row(
        _row(source_path="/work/external/llvm-project/clang/test/Sema/x.cpp"),
        verifier,
        source_index={},
    )
    assert result.status == "test_source"
    assert result.record is None
    assert verifier.call_log == []


def test_repair_row_round_trip_keeps_slice_fields():
    verifier = MockVerifier(
        lambda src, cmd, logical: (
            ok_result() if src.endswith(";\n") else
            VerifierResult(False, _diag(), "error")
        )
    )
    rec = canonicalize_row(
        _row(cascade_size=12, primary_matches_target=False),
        verifier,
        source_index={},
    ).record
    row = to_repair_row(rec)
    assert row["instance_id"] == "realinject-1"
    assert row["cascade_size"] == 1  # recomputed from this verification stderr
    assert row["generation_label"] == "exact_target"
    assert row["source_path"] == "clang/lib/Sema/SemaThing.cpp"
    assert row["compile_cmd"][-1] == "__SRC__"


def test_portable_source_path_strips_checkout_prefix():
    assert portable_source_path(
        "/a/b/external/llvm-project/clang/lib/AST/AST.cpp"
    ) == "clang/lib/AST/AST.cpp"


def test_portable_source_path_uses_explicit_project_root():
    assert portable_source_path(
        "/p/lustre2/user/opengda/src/network/ofi.cpp",
        source_root="/p/lustre2/user/opengda",
    ) == "src/network/ofi.cpp"


def test_portable_source_path_rejects_path_outside_explicit_root():
    import pytest

    with pytest.raises(ValueError, match="outside source root"):
        portable_source_path(
            "/p/lustre2/user/other/src/file.cpp",
            source_root="/p/lustre2/user/opengda",
        )
