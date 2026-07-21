from __future__ import annotations

import json

from gen.fuzzlang_dsl import run_prepare_retry as cli
from gen.fuzzlang_dsl.retry import select_retry_requests


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
