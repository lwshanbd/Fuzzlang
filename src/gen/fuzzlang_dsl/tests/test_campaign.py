from __future__ import annotations

import hashlib
from dataclasses import replace

from foundation.record import Origin, Provenance, Record, Split
from foundation.types import DiagInfo, VerifierResult
from gen.fuzzlang_dsl import campaign
from gen.fuzzlang_dsl.campaign import CampaignBudget, run_campaign
from gen.fuzzlang_dsl.injector import FuzzLangInjector, ReplayLimits
from gen.realcorpus.clean_source_pool import CleanSourceTU


def _diag(name: str, *, diag_id: int = 101, file: str = "src/unit.cpp") -> DiagInfo:
    return DiagInfo(
        diag_id=diag_id,
        diag_name=name,
        diag_msg=name,
        file=file,
        line=1,
        col=1,
        start_byte=0,
        end_byte=1,
        span_snippet="x",
    )


def _source_record(
    record_id: str,
    source: str,
    *,
    path: str = "llvm/lib/Core.cpp",
    language: str = "c++",
    corrected: str = "int f() { return 0; }\n",
) -> Record:
    standard = "-std=c11" if language == "c" else "-std=c++20"
    return Record(
        record_id=record_id,
        erroneous_src="int f() { return missing; }\n",
        corrected_src=corrected,
        diagnostics=(_diag("err_parent", file=path),),
        provenance=Provenance(
            Origin.REAL,
            source,
            {
                "project": source.split(":", 1)[0],
                "source_path": path,
                "compile_cmd": ["__CLANG__", standard, "-fsyntax-only", "__SRC__"],
            },
        ),
        split=Split.TRAIN,
        language=language,
    )


def _injector(
    replacement: str,
    *,
    target: str = "err_target",
    language: str = "c++",
    max_verifications: int = 20,
) -> FuzzLangInjector:
    return FuzzLangInjector(
        target_diag=target,
        target_diag_id=101,
        language=language,
        operation="replace",
        old_patterns=("<NUM>",),
        new_text=replacement,
        left_context=("return",),
        right_context=(";",),
        portable=True,
        replacement_parts=(("literal", replacement),),
        limits=ReplayLimits(
            max_edit_chars=64,
            max_candidates=4,
            max_verifications=max_verifications,
        ),
    )


class _FakeVerifier:
    def __init__(self, *, dirty_corrected: str | None = None):
        self.calls: list[tuple[str, tuple[str, ...], str]] = []
        self.dirty_corrected = dirty_corrected

    def verify(self, source: str, compile_cmd: list[str], *, logical_path: str):
        self.calls.append((source, tuple(compile_cmd), logical_path))
        if source == self.dirty_corrected:
            return VerifierResult(False, _diag("err_unclean", file=logical_path), "unclean")
        if "bad_exact" in source:
            return VerifierResult(False, _diag("err_target", file=logical_path), "exact")
        if "bad_other" in source:
            return VerifierResult(False, _diag("err_other", file=logical_path), "other")
        return VerifierResult(True, None, "")


def test_campaign_emits_only_exact_target_canonical_paired_records():
    source = _source_record("parent-1", "llvm:llvm/lib/Core.cpp")
    verifier = _FakeVerifier()

    result = run_campaign(
        [_injector("bad_exact"), _injector("bad_other"), _injector("still_valid")],
        [source],
        verifier,
        budget=CampaignBudget(
            max_verifications=20,
            max_verifications_per_injector=10,
            max_candidates_per_source=2,
            max_records=20,
            max_records_per_injector=10,
        ),
    )

    assert len(result.records) == 1
    record = result.records[0]
    assert record.corrected_src == source.corrected_src
    assert record.primary_diagnostic.diag_name == "err_target"
    assert record.provenance.origin is Origin.MUTATE
    assert record.provenance.source == source.provenance.source
    assert record.provenance.detail["strategy"] == "synthesized_injector_campaign"
    assert record.provenance.detail["primary_matches_target"] is True
    assert record.provenance.detail["parent_record_id"] == "parent-1"
    assert record.split is Split.TRAIN

    metrics = {item.injector_id: item for item in result.injector_metrics}
    exact, near, clean = [_injector(value).injector_id for value in (
        "bad_exact", "bad_other", "still_valid",
    )]
    assert metrics[exact].to_dict() == {
        "injector_id": exact,
        "target_diag": "err_target",
        "considered": 1,
        "matched": 1,
        "candidates": 1,
        "compiled": 1,
        "exact_target": 1,
        "records_emitted": 1,
        "duplicate_exact": 0,
        "near_miss": 0,
        "clean": 0,
        "unique_TUs": 1,
        "projects": 1,
        "target_rate": 1.0,
    }
    assert metrics[near].near_miss == 1
    assert metrics[clean].clean == 1
    assert {rejection.status for rejection in result.rejections} == {
        "near_miss", "candidate_clean",
    }


def test_campaign_requires_target_diagnostic_id_when_injector_carries_one():
    source = _source_record("parent-id", "llvm:llvm/lib/DiagID.cpp")
    wrong_id = replace(_injector("bad_exact"), target_diag_id=999)

    result = run_campaign(
        [wrong_id], [source], _FakeVerifier(),
        budget=CampaignBudget(max_verifications=4),
    )

    assert result.records == ()
    assert result.injector_metrics[0].near_miss == 1
    assert result.injector_metrics[0].exact_target == 0


def test_source_pool_excludes_tests_deduplicates_provenance_and_clean_gates_once():
    clean = _source_record("good", "llvm:llvm/lib/Good.cpp", path="llvm/lib/Good.cpp")
    duplicate = replace(clean, record_id="duplicate")
    test_source = _source_record(
        "test", "llvm:clang/test/Sema/nope.cpp", path="clang/test/Sema/nope.cpp",
    )
    test_support = _source_record(
        "support", "llvm:llvm/lib/TestingSupport.cpp", path="llvm/lib/TestingSupport.cpp",
    )
    dirty = _source_record(
        "dirty", "llvm:llvm/lib/Dirty.cpp", path="llvm/lib/Dirty.cpp",
        corrected="int dirty() { return 0; }\n",
    )
    verifier = _FakeVerifier(dirty_corrected=dirty.corrected_src)

    result = run_campaign(
        [_injector("bad_exact"), _injector("bad_other")],
        [clean, duplicate, test_source, test_support, dirty],
        verifier,
        budget=CampaignBudget(max_verifications=20),
    )

    baseline_calls = [call for call in verifier.calls if "bad_" not in call[0]]
    assert [call[0] for call in baseline_calls].count(clean.corrected_src) == 1
    assert [call[0] for call in baseline_calls].count(dirty.corrected_src) == 1
    assert {record.provenance.source for record in result.records} == {
        "llvm:llvm/lib/Good.cpp",
    }
    statuses = [rejection.status for rejection in result.rejections]
    assert statuses.count("duplicate_source") == 1
    assert statuses.count("test_source") == 2
    assert statuses.count("corrected_not_clean") == 1
    assert all("test" not in record.provenance.source.lower() for record in result.records)


def test_campaign_enforces_global_and_per_injector_verification_budgets():
    sources = [
        _source_record(
            f"p-{index}", f"llvm:llvm/lib/F{index}.cpp", path=f"llvm/lib/F{index}.cpp",
        )
        for index in range(4)
    ]
    first = _injector("bad_exact", target="err_target", max_verifications=10)
    second = _injector("bad_other", target="err_other", max_verifications=10)

    result = run_campaign(
        [first, second],
        sources,
        _FakeVerifier(),
        budget=CampaignBudget(
            max_verifications=3,
            max_verifications_per_injector=2,
            max_candidates_per_source=1,
            max_records=10,
            max_records_per_injector=10,
        ),
    )

    metrics = {item.injector_id: item for item in result.injector_metrics}
    assert metrics[first.injector_id].compiled == 2
    assert metrics[second.injector_id].compiled == 1
    assert result.budget_usage["mutant_verifications"] == 3
    assert result.budget_usage["baseline_verifications"] <= len(sources)
    assert result.budget_usage["records"] == 3


def test_campaign_bounds_real_source_scan_per_injector():
    sources = [
        _source_record(
            f"source-{index}",
            f"llvm:llvm/lib/Bounded{index}.cpp",
            path=f"llvm/lib/Bounded{index}.cpp",
        )
        for index in range(4)
    ]

    result = run_campaign(
        [_injector("bad_exact")], sources, _FakeVerifier(),
        budget=CampaignBudget(
            max_verifications=20,
            max_verifications_per_injector=20,
            max_candidates_per_source=1,
            max_records=20,
            max_records_per_injector=20,
            max_sources_per_injector=2,
        ),
    )

    assert result.injector_metrics[0].considered == 2
    assert result.injector_metrics[0].records_emitted == 2


def test_campaign_uses_language_matched_sources_and_preserves_compile_commands():
    c_source = _source_record(
        "c-parent", "postgres:src/backend/main.c", path="src/backend/main.c",
        language="c", corrected="int f(void) { return 0; }\n",
    )
    cpp_source = _source_record(
        "cpp-parent", "llvm:llvm/lib/Main.cpp", path="llvm/lib/Main.cpp",
        language="c++",
    )
    verifier = _FakeVerifier()

    result = run_campaign(
        [_injector("bad_exact", language="c"), _injector("bad_exact", language="c++")],
        [c_source, cpp_source],
        verifier,
        budget=CampaignBudget(max_verifications=10),
    )

    assert len(result.records) == 2
    by_language = {record.language: record for record in result.records}
    assert by_language["c"].provenance.detail["compile_cmd"] == [
        "__CLANG__", "-std=c11", "-fsyntax-only", "__SRC__",
    ]
    assert by_language["c++"].provenance.detail["compile_cmd"] == [
        "__CLANG__", "-std=c++20", "-fsyntax-only", "__SRC__",
    ]
    assert all(item.considered == 1 for item in result.injector_metrics)


def test_campaign_does_not_baseline_compile_sources_without_a_lexical_match():
    source = _source_record(
        "unmatched",
        "llvm:llvm/lib/NoReturn.cpp",
        path="llvm/lib/NoReturn.cpp",
        corrected="void f() {}\n",
    )
    verifier = _FakeVerifier()

    result = run_campaign(
        [_injector("bad_exact")],
        [source],
        verifier,
        budget=CampaignBudget(max_verifications=4),
    )

    assert verifier.calls == []
    assert result.budget_usage["baseline_verifications"] == 0
    assert result.injector_metrics[0].considered == 1
    assert result.injector_metrics[0].matched == 0


def test_invalid_duplicate_does_not_poison_later_valid_source_identity():
    valid = _source_record(
        "valid", "llvm:llvm/lib/Later.cpp", path="llvm/lib/Later.cpp",
    )
    invalid = replace(
        valid,
        record_id="invalid-first",
        provenance=Provenance(
            Origin.REAL,
            valid.provenance.source,
            {
                "project": "llvm",
                "source_path": "llvm/lib/Later.cpp",
                "compile_cmd": ["not-a-placeholder-command"],
            },
        ),
    )

    result = run_campaign(
        [_injector("bad_exact")], [invalid, valid], _FakeVerifier(),
        budget=CampaignBudget(max_verifications=4),
    )

    assert len(result.records) == 1
    assert [item.status for item in result.rejections] == ["invalid_compile_cmd"]


def test_campaign_can_replay_a_clean_source_pool_without_fabricating_parent_record():
    corrected = "int f() { return 0; }\n"
    source = CleanSourceTU(
        source_id="llvm:llvm/lib/IR/Clean.cpp",
        project="llvm",
        source_path="llvm/lib/IR/Clean.cpp",
        language="c++",
        corrected_src=corrected,
        compile_cmd=("__CLANG__", "-std=c++20", "-fsyntax-only", "__SRC__"),
        source_sha256=hashlib.sha256(corrected.encode()).hexdigest(),
        baseline_compiler="llvmorg-22.1.8",
    )

    result = run_campaign(
        [_injector("bad_exact")], [], _FakeVerifier(), clean_sources=[source],
        budget=CampaignBudget(max_verifications=4),
    )

    assert len(result.records) == 1
    record = result.records[0]
    assert record.corrected_src == corrected
    assert record.provenance.source == source.source_id
    assert record.provenance.detail["source_pool"] == "clean_source_tu"
    assert record.provenance.detail["source_sha256"] == source.source_sha256
    assert "parent_record_id" not in record.provenance.detail
    assert result.source_pool["input_clean_sources"] == 1


def test_campaign_reuses_source_tokenization_across_injectors(monkeypatch):
    source = _source_record("parent-cache", "llvm:llvm/lib/Cache.cpp")
    original = campaign.lex_tokens
    calls = 0

    def counted(text):
        nonlocal calls
        calls += 1
        return original(text)

    monkeypatch.setattr(campaign, "lex_tokens", counted)
    result = run_campaign(
        [_injector("bad_exact"), _injector("bad_other")],
        [source],
        _FakeVerifier(),
        budget=CampaignBudget(max_verifications=4),
    )

    assert len(result.records) == 1
    assert calls == 1
