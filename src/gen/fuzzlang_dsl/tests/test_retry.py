from __future__ import annotations

import hashlib
import json

from gen.fuzzlang_dsl import run_prepare_retry as cli
from gen.fuzzlang_dsl import run_prepare_replay_retry as replay_cli
from gen.fuzzlang_dsl.injector import FuzzLangInjector, ReplayLimits, apply_injector
from gen.fuzzlang_dsl.retry import (
    build_near_miss_witness_evidence,
    select_replay_retry_requests,
    select_retry_requests,
)
from gen.realcorpus.clean_source_pool import CleanSourceTU


def _request(name: str, diag_id: int) -> dict:
    return {
        "diag_name": name,
        "diag_id": diag_id,
        "diag_message": "message",
        "component": "Parse",
        "language": "c++",
        "tablegen_definition": "def err : Error<\"message\">;",
        "emission_evidence": "compiler evidence",
        "correct_snippets": ["int f() { return 0; }", "int g() { return 1; }"],
    }


def test_near_miss_evidence_reconstructs_verified_replay_pair():
    injector = FuzzLangInjector(
        target_diag="err_target",
        target_diag_id=1,
        language="c++",
        operation="replace",
        old_patterns=("<NUM>",),
        new_text="broken",
        left_context=("return",),
        right_context=(";",),
        portable=True,
        replacement_parts=(("literal", "broken"),),
        limits=ReplayLimits(max_edit_chars=64, max_candidates=2, max_verifications=8),
    )
    corrected = "int f() { return 0; }\n"
    source = CleanSourceTU(
        source_id="demo:lib/f.cc",
        project="demo",
        source_path="lib/f.cc",
        language="c++",
        corrected_src=corrected,
        compile_cmd=("__CLANG__", "-fsyntax-only", "__SRC__"),
        source_sha256=hashlib.sha256(corrected.encode()).hexdigest(),
        baseline_compiler="llvmorg-22.1.8",
    )
    application = apply_injector(corrected, injector, max_candidates=1)[0]

    result = build_near_miss_witness_evidence(
        [injector.to_dict()],
        [source],
        [{
            "status": "near_miss",
            "injector_id": injector.injector_id,
            "provenance_source": source.source_id,
            "candidate_index": 0,
            "candidate_sha256": hashlib.sha256(application.src.encode()).hexdigest(),
            "observed_diag": "err_observed_instead",
        }],
    )

    assert list(result) == [injector.injector_id]
    evidence = result[injector.injector_id]
    assert "not target-validated" in evidence
    assert "err_observed_instead" in evidence
    assert "Correct local code window:" in evidence
    assert "Mutated local code window:" in evidence
    assert "return 0" in evidence
    assert "return broken" in evidence


def test_select_retry_requests_keeps_only_attempted_without_any_acceptance():
    requests = [_request("err_accepted", 1), _request("err_rejected", 2), _request("err_unattempted", 3)]
    attempts = [
        {"diag_name": "err_accepted", "status": "accepted", "reason": None},
        {"diag_name": "err_rejected", "status": "rejected", "reason": "no_exemplar_match"},
        {"diag_name": "err_rejected", "status": "rejected", "reason": "schema_validation"},
    ]

    selected, summary = select_retry_requests(requests, attempts)

    assert [row["diag_name"] for row in selected] == ["err_rejected"]
    assert "no_exemplar_match" in selected[0]["emission_evidence"]
    assert "exact lexer tokens" in selected[0]["emission_evidence"]
    assert summary == {
        "requests": 3,
        "attempted_targets": 2,
        "accepted_targets": 1,
        "retry_targets": 1,
        "unattempted_targets": 1,
    }


def test_retry_cli_writes_deterministic_rows_and_manifest(tmp_path):
    requests = tmp_path / "requests.jsonl"
    attempts = tmp_path / "attempts.jsonl"
    output = tmp_path / "retry.jsonl"
    manifest = tmp_path / "retry.manifest.json"
    requests.write_text("".join(
        json.dumps(row, sort_keys=True) + "\n"
        for row in (_request("err_one", 1), _request("err_two", 2))
    ))
    attempts.write_text("\n".join([
        json.dumps({"diag_name": "err_one", "status": "accepted", "reason": None}),
        json.dumps({"diag_name": "err_two", "status": "rejected", "reason": "no_exemplar_match"}),
    ]) + "\n")

    assert cli.main([
        "--requests", str(requests),
        "--attempts", str(attempts),
        "--out", str(output),
        "--manifest-out", str(manifest),
    ]) == 0

    rows = [json.loads(line) for line in output.read_text().splitlines()]
    payload = json.loads(manifest.read_text())
    assert [row["diag_name"] for row in rows] == ["err_two"]
    assert payload["selection"]["retry_targets"] == 1
    assert payload["outputs"]["requests"]["records"] == 1


def test_select_replay_retry_requests_uses_compiler_feedback_and_prior_injector():
    requests = [_request("err_target", 1), _request("err_emitted", 2)]
    injectors = [
        {
            "injector_id": "injector-near-miss",
            "target": {"diag_name": "err_target", "diag_id": 1},
            "match": {"left_context": ["return"]},
        },
        {
            "injector_id": "injector-exact",
            "target": {"diag_name": "err_emitted", "diag_id": 2},
            "match": {"left_context": ["return"]},
        },
    ]
    manifests = [{
        "injectors": [
            {
                "injector_id": "injector-near-miss",
                "target_diag": "err_target",
                "compiled": 3,
                "exact_target": 0,
                "records_emitted": 0,
            },
            {
                "injector_id": "injector-exact",
                "target_diag": "err_emitted",
                "compiled": 3,
                "exact_target": 2,
                "records_emitted": 2,
            },
        ],
    }]
    rejections = [
        {
            "injector_id": "injector-near-miss",
            "reason": "primary diagnostic did not exactly match Injector target",
            "observed_diag": "err_observed_instead",
        },
    ]

    selected, summary = select_replay_retry_requests(
        requests, injectors, manifests, rejections,
        near_miss_evidence_by_injector={
            "injector-near-miss": "Compiler replay near-miss evidence (not target-validated): pair",
        },
    )

    assert [row["diag_name"] for row in selected] == ["err_target"]
    feedback = selected[0]["emission_evidence"]
    assert "err_observed_instead" in feedback
    assert '"injector_id"' not in feedback
    assert '"target"' in feedback
    assert "differ in at least one match or edit field" in feedback
    assert "not target-validated" in feedback
    assert summary["retry_targets"] == 1
    assert summary["targets_with_exact_records"] == 1


def test_replay_retry_cli_writes_compiler_feedback_requests(tmp_path):
    requests = tmp_path / "requests.jsonl"
    injectors = tmp_path / "injectors.jsonl"
    campaign = tmp_path / "campaign.json"
    rejections = tmp_path / "rejections.jsonl"
    output = tmp_path / "retry.jsonl"
    manifest = tmp_path / "retry.manifest.json"
    requests.write_text(json.dumps(_request("err_target", 1)) + "\n")
    injectors.write_text(json.dumps({
        "injector_id": "injector-near-miss",
        "target": {"diag_name": "err_target", "diag_id": 1},
    }) + "\n")
    campaign.write_text(json.dumps({"injectors": [{
        "injector_id": "injector-near-miss",
        "target_diag": "err_target",
        "compiled": 1,
        "exact_target": 0,
        "records_emitted": 0,
    }]}))
    rejections.write_text(json.dumps({
        "injector_id": "injector-near-miss",
        "observed_diag": "err_observed_instead",
    }) + "\n")

    assert replay_cli.main([
        "--requests", str(requests),
        "--injectors", str(injectors),
        "--campaign-manifest", str(campaign),
        "--rejections", str(rejections),
        "--out", str(output),
        "--manifest-out", str(manifest),
    ]) == 0

    rows = [json.loads(line) for line in output.read_text().splitlines()]
    payload = json.loads(manifest.read_text())
    assert [row["diag_name"] for row in rows] == ["err_target"]
    assert "err_observed_instead" in rows[0]["emission_evidence"]
    assert payload["selection"]["retry_targets"] == 1
    assert payload["outputs"]["requests"]["records"] == 1


def test_replay_retry_cli_can_attach_reconstructed_near_miss_pair(tmp_path):
    corrected = "int f() { return 0; }\n"
    source = CleanSourceTU(
        source_id="demo:lib/f.cc",
        project="demo",
        source_path="lib/f.cc",
        language="c++",
        corrected_src=corrected,
        compile_cmd=("__CLANG__", "-fsyntax-only", "__SRC__"),
        source_sha256=hashlib.sha256(corrected.encode()).hexdigest(),
        baseline_compiler="llvmorg-22.1.8",
    )
    injector = FuzzLangInjector(
        target_diag="err_target",
        target_diag_id=1,
        language="c++",
        operation="replace",
        old_patterns=("<NUM>",),
        new_text="broken",
        left_context=("return",),
        right_context=(";",),
        portable=True,
        replacement_parts=(("literal", "broken"),),
        limits=ReplayLimits(max_edit_chars=64, max_candidates=2, max_verifications=8),
    )
    application = apply_injector(corrected, injector, max_candidates=1)[0]
    requests = tmp_path / "requests.jsonl"
    injectors = tmp_path / "injectors.jsonl"
    campaign = tmp_path / "campaign.json"
    rejections = tmp_path / "rejections.jsonl"
    clean_sources = tmp_path / "sources.jsonl"
    output = tmp_path / "retry.jsonl"
    manifest = tmp_path / "retry.manifest.json"
    requests.write_text(json.dumps(_request("err_target", 1)) + "\n")
    injectors.write_text(json.dumps(injector.to_dict()) + "\n")
    campaign.write_text(json.dumps({"injectors": [{
        "injector_id": injector.injector_id,
        "target_diag": "err_target",
        "compiled": 1,
        "exact_target": 0,
        "records_emitted": 0,
    }]}))
    rejections.write_text(json.dumps({
        "status": "near_miss",
        "injector_id": injector.injector_id,
        "provenance_source": source.source_id,
        "candidate_index": 0,
        "candidate_sha256": hashlib.sha256(application.src.encode()).hexdigest(),
        "observed_diag": "err_observed_instead",
    }) + "\n")
    clean_sources.write_text(json.dumps(source.to_dict()) + "\n")

    assert replay_cli.main([
        "--requests", str(requests),
        "--injectors", str(injectors),
        "--campaign-manifest", str(campaign),
        "--rejections", str(rejections),
        "--clean-sources", str(clean_sources),
        "--out", str(output),
        "--manifest-out", str(manifest),
    ]) == 0

    row = json.loads(output.read_text())
    payload = json.loads(manifest.read_text())
    assert "not target-validated" in row["emission_evidence"]
    assert payload["near_miss_witnesses"] == 1
    assert payload["inputs"]["clean_sources"]["records"] == 1
