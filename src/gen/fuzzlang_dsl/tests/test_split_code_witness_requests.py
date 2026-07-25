from __future__ import annotations

import json

from gen.fuzzlang_dsl.run_split_code_witness_requests import split_requests


def _row(name: str, *, evidence: bool = False) -> dict:
    return {
        "diag_name": name,
        "emission_evidence": "evidence" if evidence else None,
    }


def test_split_requests_writes_fixed_size_auditable_batches(tmp_path):
    rows = [_row(f"err_{index}", evidence=index % 2 == 0) for index in range(5)]

    summary = split_requests(
        rows,
        output_root=tmp_path,
        label_start=501,
        batch_size=2,
        campaign="broad-emission-gap-v1",
    )

    assert summary == {"batches": 3, "requests": 5, "first_label": 501, "last_label": 503}
    first = json.loads(
        (tmp_path / "coverage-first-v0501" / "request-manifest.json").read_text()
    )
    final_rows = [
        json.loads(line)
        for line in (tmp_path / "coverage-first-v0503" / "requests.jsonl").read_text().splitlines()
    ]
    assert first["campaign"] == "broad-emission-gap-v1"
    assert first["counts"]["requests"] == 2
    assert first["counts"]["targets_with_emission_evidence"] == 1
    assert [row["diag_name"] for row in final_rows] == ["err_4"]
