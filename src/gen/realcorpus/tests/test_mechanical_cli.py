from __future__ import annotations

import json
import sys

from foundation.record import Record
from foundation.verifier.mock import MockVerifier, ok_result
from gen.realcorpus.tests.test_mechanical import CORRECT, _error_result, _parent


def test_mechanical_cli_writes_records_rejections_and_compile_manifest(
    tmp_path, monkeypatch,
):
    import gen.realcorpus.run_mechanical_realsource as cli

    input_path = tmp_path / "parents.jsonl"
    input_path.write_text("\n".join([
        json.dumps(_parent("parent-1").to_dict()),
        json.dumps(_parent("parent-2").to_dict()),
    ]) + "\n")
    output = tmp_path / "records.jsonl"
    rejected = tmp_path / "rejected.jsonl"
    manifest = tmp_path / "manifest.json"
    verifier = MockVerifier(
        lambda src, cmd, path: ok_result() if src == CORRECT else _error_result()
    )
    monkeypatch.setattr(
        cli, "FuzzlangClangVerifier", lambda *args, **kwargs: verifier
    )
    monkeypatch.setattr(sys, "argv", [
        "run_mechanical_realsource.py",
        "--input", str(input_path),
        "--clang-bin", "/unused/clang",
        "--clang-c-bin", "/unused/clang-c",
        "--diagtool-bin", "/unused/diagtool",
        "--out", str(output),
        "--rejected-out", str(rejected),
        "--manifest-out", str(manifest),
        "--mutation", "delete_semicolon",
        "--seed", "11",
        "--max-sources", "1",
        "--workers", "1",
        "--max-candidates-per-mutation", "1",
        "--max-verifications-per-source", "1",
        "--max-records-per-source", "1",
        "--max-instances-per-diagnostic", "2",
        "--max-instances", "2",
    ])

    cli.main()

    rows = [
        Record.from_dict(json.loads(line))
        for line in output.read_text().splitlines()
    ]
    assert len(rows) == 1
    assert rows[0].provenance.detail["strategy"] == "mechanical_real_source"
    rejection_rows = [
        json.loads(line) for line in rejected.read_text().splitlines()
    ]
    assert any(row["status"] == "duplicate_source" for row in rejection_rows)
    report = json.loads(manifest.read_text())
    assert report["generator"] == "mechanical_real_source"
    assert report["uses_llm_api"] is False
    assert report["selection"]["statuses"] == {
        "duplicate_source": 1,
        "selected": 1,
    }
    assert report["compilation"] == {
        "baseline_compiles": 1,
        "mutant_compiles": 1,
        "total_compiles": 2,
    }
    assert report["run"]["accepted"] == 1
    assert report["run"]["test_sources"] == 0
    assert report["limits"]["max_candidates_per_mutation"] == 1
    assert report["files"]["records"]["records"] == 1
    assert report["files"]["rejected"]["records"] >= 1
    assert report["inputs"]["files"][0]["bytes"] == input_path.stat().st_size
    assert len(report["inputs"]["files"][0]["sha256"]) == 64
    assert report["compiler"]["clang_bin"] == "/unused/clang"
    assert report["compiler"]["clang_c_bin"] == "/unused/clang-c"


def test_mechanical_cli_counts_whole_submitted_chunk_after_global_cap(
    tmp_path, monkeypatch,
):
    import gen.realcorpus.run_mechanical_realsource as cli

    input_path = tmp_path / "parents.jsonl"
    input_path.write_text("\n".join([
        json.dumps(_parent("a").to_dict()),
        json.dumps(_parent(
            "b",
            source="llvm:llvm/lib/B.cpp",
            source_path="llvm/lib/B.cpp",
        ).to_dict()),
    ]) + "\n")
    output = tmp_path / "records.jsonl"
    rejected = tmp_path / "rejected.jsonl"
    manifest = tmp_path / "manifest.json"
    verifier = MockVerifier(
        lambda src, cmd, path: ok_result() if src == CORRECT else _error_result()
    )
    monkeypatch.setattr(
        cli, "FuzzlangClangVerifier", lambda *args, **kwargs: verifier
    )
    monkeypatch.setattr(sys, "argv", [
        "run_mechanical_realsource.py",
        "--input", str(input_path),
        "--clang-bin", "/unused/clang++",
        "--clang-c-bin", "/unused/clang",
        "--diagtool-bin", "/unused/diagtool",
        "--out", str(output),
        "--rejected-out", str(rejected),
        "--manifest-out", str(manifest),
        "--mutation", "delete_semicolon",
        "--max-sources", "2",
        "--workers", "2",
        "--max-candidates-per-mutation", "1",
        "--max-verifications-per-source", "1",
        "--max-records-per-source", "1",
        "--max-instances-per-diagnostic", "2",
        "--max-instances", "1",
    ])

    cli.main()

    report = json.loads(manifest.read_text())
    assert report["run"]["sources_scanned"] == 2
    assert report["compilation"]["baseline_compiles"] == 2
    assert report["compilation"]["mutant_compiles"] == 2
    assert report["compilation"]["total_compiles"] == 4
    assert report["run"]["accepted_before_global_caps"] == 2
    assert report["run"]["accepted"] == 1
    rejection_statuses = [
        json.loads(line)["status"]
        for line in rejected.read_text().splitlines()
    ]
    assert "global_record_cap" in rejection_statuses
