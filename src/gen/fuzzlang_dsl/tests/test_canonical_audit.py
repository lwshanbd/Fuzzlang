from __future__ import annotations

import json

import pytest

from foundation.diagnostics.catalog import Catalog, DiagEntry
from foundation.record import Origin, Provenance, Record, Split
from foundation.types import DiagInfo
from gen.fuzzlang_dsl.canonical_audit import (
    AuditInput, build_canonical_audit, diagnostic_record_rows,
)
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
    project: str = "llvm",
    strategy: str = "gemma_code_witness_bootstrap",
    injector_id: str | None = None,
) -> Record:
    detail = {
        "source_path": source_path,
        "target_diag": target,
        "primary_matches_target": primary == target,
        "strategy": strategy,
        "project": project,
    }
    if injector_id is not None:
        detail["injector_id"] = injector_id
    return Record(
        record_id=f"record-{target}-{source_path}-{strategy}",
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
            source=f"{project}:{source_path}",
            detail=detail,
        ),
        split=Split.TRAIN,
    )


def _catalog() -> Catalog:
    return Catalog((
        DiagEntry(
            name="err_target", component="Sema", severity="Error",
            message="target", default_error=True,
        ),
        DiagEntry(
            name="err_second", component="Parse", severity="Error",
            message="second", default_error=True,
        ),
        DiagEntry(
            name="err_uncovered", component="Sema", severity="Error",
            message="uncovered", default_error=True,
        ),
        DiagEntry(
            name="err_driver_only", component="Driver", severity="Error",
            message="driver", default_error=True,
        ),
    ))


def _write_jsonl(path, values) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(
        json.dumps(value.to_dict(), sort_keys=True) + "\n" for value in values
    ))


def _campaign(tmp_path, label, injectors, records) -> AuditInput:
    directory = tmp_path / label
    injector_path, record_path = directory / "injectors.jsonl", directory / "records.jsonl"
    _write_jsonl(injector_path, injectors)
    _write_jsonl(record_path, records)
    return AuditInput(label=label, injector_path=injector_path, record_path=record_path)


def test_canonical_audit_unions_campaigns_and_freezes_input_checksums(tmp_path):
    first = _campaign(tmp_path, "b01", [_injector()], [_record()])
    second = _campaign(
        tmp_path, "b02", [_injector("err_second", 18)],
        [_record(
            target="err_second", primary="err_second", diag_id=18,
            source_path="clang/lib/Parse/Other.cpp",
        )],
    )

    audit = build_canonical_audit(
        [first, second], catalog=_catalog(), out_of_scope=frozenset(),
        base_verified_names=frozenset({"err_target"}), base_label="batch0006",
    )

    assert audit["schema"] == "fuzzlang.canonical_strict_injector_audit.v1"
    assert audit["counts"]["strict_verified_records"] == 2
    assert audit["counts"]["verified_diagnostic_types"] == 2
    # Driver is an invocation component and is excluded from the paper scope.
    assert audit["paper_scope"]["total_diagnostic_types"] == 3
    assert audit["paper_scope"]["verified_diagnostic_types"] == 2
    assert audit["paper_scope"]["new_vs_base_diagnostic_names"] == ["err_second"]
    manifest = audit["input_manifest"]
    assert [row["label"] for row in manifest] == ["b01", "b01", "b02", "b02"]
    assert {row["kind"] for row in manifest} == {"injectors", "records"}
    assert all(len(row["sha256"]) == 64 and row["rows"] == 1 for row in manifest)


def test_canonical_audit_deduplicates_repeated_input_paths(tmp_path):
    campaign = _campaign(tmp_path, "b01", [_injector()], [_record()])
    repeated = AuditInput(
        label="b01-again",
        injector_path=campaign.injector_path,
        record_path=campaign.record_path,
    )

    audit = build_canonical_audit(
        [campaign, repeated], catalog=_catalog(), out_of_scope=frozenset(),
        base_verified_names=frozenset(), base_label="batch0006",
    )

    assert audit["counts"]["input_record_rows"] == 1
    assert len(audit["input_manifest"]) == 2
    assert audit["duplicate_input_paths"] == [
        str(campaign.injector_path), str(campaign.record_path),
    ]


def test_canonical_audit_excludes_out_of_scope_names_from_the_paper_numerator(tmp_path):
    campaign = _campaign(tmp_path, "b01", [_injector()], [_record()])

    audit = build_canonical_audit(
        [campaign], catalog=_catalog(), out_of_scope=frozenset({"err_target"}),
        base_verified_names=frozenset(), base_label="batch0006",
    )

    assert audit["counts"]["verified_diagnostic_types"] == 1
    assert audit["paper_scope"]["verified_diagnostic_types"] == 0
    assert audit["paper_scope"]["total_diagnostic_types"] == 2


def test_canonical_audit_maps_each_diagnostic_to_records_injectors_and_campaigns(tmp_path):
    injector = _injector()
    campaign = _campaign(
        tmp_path, "b01", [injector],
        [
            _record(),
            _record(
                source_path="clang/lib/Sema/Second.cpp",
                strategy="gemma_code_witness_injector_replay",
                injector_id=injector.injector_id,
            ),
        ],
    )
    other = _campaign(
        tmp_path, "b02", [injector],
        [_record(source_path="absl/strings/str_cat.cc", project="abseil")],
    )

    audit = build_canonical_audit(
        [campaign, other], catalog=_catalog(), out_of_scope=frozenset(),
        base_verified_names=frozenset(), base_label="batch0006",
    )
    index = audit["diagnostic_index"]["err_target"]

    assert index["strict_records"] == 3
    assert index["source_tus"] == 3
    assert index["projects"] == ["abseil", "llvm"]
    assert index["campaigns"] == ["b01", "b02"]
    assert index["injector_ids"] == [injector.injector_id]
    assert index["in_paper_scope"] is True
    assert index["component"] == "Sema"

    rows = diagnostic_record_rows(audit)
    assert [row["diag_name"] for row in rows] == ["err_target"]
    assert rows[0]["projects"] == "abseil|llvm"


def test_canonical_audit_reports_rejections_and_never_counts_test_sources(tmp_path):
    campaign = _campaign(
        tmp_path, "b01", [_injector()],
        [
            _record(source_path="clang/test/Sema/bad.cpp"),
            _record(target="err_uncovered", primary="err_uncovered"),
        ],
    )

    audit = build_canonical_audit(
        [campaign], catalog=_catalog(), out_of_scope=frozenset(),
        base_verified_names=frozenset(), base_label="batch0006",
    )

    assert audit["counts"]["verified_diagnostic_types"] == 0
    assert audit["rejections"] == {
        "missing_portable_injector": 1,
        "test_or_test_support_source": 1,
    }
    assert audit["diagnostic_index"] == {}


def test_canonical_audit_excludes_opportunistically_relabelled_targets(tmp_path):
    """A record whose target was rewritten to the observed diagnostic is not a
    goal-directed result, so the headline numerator must not claim it."""
    relabelled = _record(source_path="clang/lib/Sema/Relabelled.cpp")
    relabelled.provenance.detail["opportunistic_observed_diagnostic"] = True
    campaign = _campaign(tmp_path, "b01", [_injector()], [_record(), relabelled])

    strict = build_canonical_audit(
        [campaign], catalog=_catalog(), out_of_scope=frozenset(),
        base_verified_names=frozenset(), base_label="batch0006",
    )
    inclusive = build_canonical_audit(
        [campaign], catalog=_catalog(), out_of_scope=frozenset(),
        base_verified_names=frozenset(), base_label="batch0006",
        exclude_opportunistic=False,
    )

    assert strict["excludes_opportunistic_relabelled_targets"] is True
    assert strict["counts"]["strict_verified_records"] == 1
    assert strict["rejections"] == {"opportunistic_relabelled_target": 1}
    assert inclusive["counts"]["strict_verified_records"] == 2
    assert inclusive["rejections"] == {}


def test_extra_inputs_are_parsed_as_label_injector_record_triples():
    from gen.fuzzlang_dsl.run_canonical_strict_audit import parse_extra_input

    item = parse_extra_input("e1-lexical-train:/a/library.jsonl:/b/records.jsonl")
    assert item.label == "e1-lexical-train"
    assert str(item.injector_path) == "/a/library.jsonl"
    assert str(item.record_path) == "/b/records.jsonl"

    for bad in ("no-colons", "only:one-colon"):
        with pytest.raises(ValueError):
            parse_extra_input(bad)

