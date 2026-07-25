from __future__ import annotations

import json

from foundation.diagnostics.catalog import Catalog, DiagEntry
from foundation.record import Origin, Provenance, Record, Split
from foundation.types import DiagInfo
from gen.fuzzlang_dsl.coverage_audit import audit_verified_injector_coverage
from gen.fuzzlang_dsl.injector import FuzzLangInjector


def _injector(name: str = "err_target", diag_id: int = 17) -> FuzzLangInjector:
    return FuzzLangInjector(
        target_diag=name,
        target_diag_id=diag_id,
        language="c++",
        operation="replace",
        old_patterns=("<ID0>",),
        new_text="bad",
        left_context=("return",),
        right_context=(";",),
        replacement_parts=(("literal", "bad"),),
        portable=True,
    )


def _record(
    *,
    target: str = "err_target",
    primary: str = "err_target",
    diag_id: int = 17,
    source_path: str = "clang/lib/Sema/Production.cpp",
    strategy: str = "gemma_code_witness_bootstrap",
) -> Record:
    return Record(
        record_id=f"record-{target}-{source_path}",
        erroneous_src="int f(){ return bad; }\n",
        corrected_src="int f(){ return value; }\n",
        diagnostics=(DiagInfo(
            diag_id=diag_id,
            diag_name=primary,
            diag_msg="target",
            file=source_path,
            line=1,
            col=1,
            start_byte=16,
            end_byte=19,
            span_snippet="bad",
        ),),
        provenance=Provenance(
            origin=Origin.MUTATE,
            source=f"llvm:{source_path}",
            detail={
                "source_path": source_path,
                "target_diag": target,
                "primary_matches_target": primary == target,
                "strategy": strategy,
            },
        ),
        split=Split.TRAIN,
    )


def _write_jsonl(path, values) -> None:
    path.write_text("".join(
        json.dumps(value.to_dict(), sort_keys=True) + "\n"
        for value in values
    ))


def test_coverage_audit_requires_portable_injector_and_exact_paired_record(tmp_path):
    injectors = tmp_path / "injectors.jsonl"
    records = tmp_path / "records.jsonl"
    _write_jsonl(injectors, [_injector()])
    _write_jsonl(records, [_record()])

    report = audit_verified_injector_coverage([injectors], [records])

    assert report["counts"]["unique_portable_injectors"] == 1
    assert report["counts"]["strict_verified_records"] == 1
    assert report["counts"]["verified_diagnostic_types"] == 1
    assert report["verified_diagnostic_names"] == ["err_target"]
    assert report["rejections"] == {}


def test_coverage_audit_rejects_tests_wrong_primary_id_and_missing_injector(tmp_path):
    injectors = tmp_path / "injectors.jsonl"
    records = tmp_path / "records.jsonl"
    _write_jsonl(injectors, [_injector()])
    _write_jsonl(records, [
        _record(source_path="clang/test/Sema/bad.cpp"),
        _record(primary="err_other"),
        _record(diag_id=99),
        _record(target="err_without_injector", primary="err_without_injector"),
    ])

    report = audit_verified_injector_coverage([injectors], [records])

    assert report["counts"]["verified_diagnostic_types"] == 0
    assert report["rejections"] == {
        "injector_diag_id_mismatch": 1,
        "missing_portable_injector": 1,
        "primary_target_mismatch": 1,
        "test_or_test_support_source": 1,
    }


def test_coverage_audit_counts_cross_source_replay_types(tmp_path):
    injector = _injector()
    injectors = tmp_path / "injectors.jsonl"
    records = tmp_path / "records.jsonl"
    _write_jsonl(injectors, [injector])
    replay = _record(strategy="synthesized_injector_campaign")
    value = replay.to_dict()
    value["provenance"]["detail"]["injector_id"] = injector.injector_id
    records.write_text(json.dumps(value) + "\n")

    report = audit_verified_injector_coverage([injectors], [records])

    assert report["counts"]["cross_source_replay_diagnostic_types"] == 1
    assert report["cross_source_replay_diagnostic_names"] == ["err_target"]


def test_coverage_audit_requires_the_recorded_injector_for_new_witness_rows(tmp_path):
    injectors = tmp_path / "injectors.jsonl"
    records = tmp_path / "records.jsonl"
    _write_jsonl(injectors, [_injector()])
    value = _record(strategy="gemma_code_witness_injector_replay").to_dict()
    value["provenance"]["detail"]["injector_id"] = "fuzzlang-v1-missing"
    records.write_text(json.dumps(value) + "\n")

    report = audit_verified_injector_coverage([injectors], [records])

    assert report["counts"]["verified_diagnostic_types"] == 0
    assert report["rejections"] == {"recorded_injector_missing_or_mismatched": 1}


def test_coverage_audit_can_require_a_pinned_catalog_error_name(tmp_path):
    injectors = tmp_path / "injectors.jsonl"
    records = tmp_path / "records.jsonl"
    _write_jsonl(injectors, [_injector("err_not_in_catalog")])
    _write_jsonl(records, [_record(
        target="err_not_in_catalog", primary="err_not_in_catalog",
    )])
    catalog = Catalog((DiagEntry(
        name="err_other", component="Sema", severity="Error",
        message="other", default_error=True,
    ),))

    report = audit_verified_injector_coverage(
        [injectors], [records], catalog=catalog,
    )

    assert report["counts"]["strict_verified_records"] == 0
    assert report["counts"]["catalog_error_diagnostic_total"] == 1
    assert report["rejections"] == {"target_not_catalog_error_diagnostic": 1}
