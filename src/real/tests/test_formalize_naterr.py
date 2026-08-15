from __future__ import annotations

import json
from pathlib import Path

import pytest

from foundation.record import Origin, Record, Split
from foundation.types import DiagInfo, VerifierResult
from foundation.verifier.mock import MockVerifier, ok_result
from real.formalize_naterr import FormalizeResult, formalize_row
from real.run_formalize_naterr import main


BUGGY = "int main() { return missing; }\n"
CORRECTED = "int main() { return 0; }\n"
COMPILE_CMD = ["__CLANG__", "-std=c++17", "-fsyntax-only", "__SRC__"]


def _diag(name: str = "err_undeclared_var_use", diag_id: int = 123) -> DiagInfo:
    return DiagInfo(
        diag_id=diag_id,
        diag_name=name,
        diag_msg="use of undeclared identifier 'missing'",
        file="clang/lib/Foo.cpp",
        line=1,
        col=21,
        start_byte=0,
        end_byte=len(BUGGY),
        span_snippet=BUGGY.rstrip(),
    )


def _failure(name: str = "err_undeclared_var_use", diag_id: int = 123):
    return VerifierResult(ok=False, diag=_diag(name, diag_id), raw_stderr="error")


def _row(**overrides) -> dict:
    row = {
        "instance_id": "llvm-pred123-Foo-a1b2c3",
        "project": "llvm",
        "commit_sha": "pred123",
        "fix_sha": "fix456",
        "source_file": "clang/lib/Foo.cpp",
        "compile_cmd": COMPILE_CMD,
        "buggy_src": BUGGY,
        "diag_id": 123,
        "diag_name": "err_undeclared_var_use",
        "line": 1,
        "col": 21,
        "msg": "use of undeclared identifier 'missing'",
    }
    row.update(overrides)
    return row


def _good_verifier() -> MockVerifier:
    return MockVerifier(
        lambda source, cmd, path: ok_result() if source == CORRECTED else _failure()
    )


def test_formalize_recovers_fix_source_and_emits_verified_real_record(
    tmp_path: Path,
) -> None:
    source_calls = []

    def source_at(checkout: Path, revision: str, path: str):
        source_calls.append((checkout, revision, path))
        return CORRECTED, ""

    verifier = _good_verifier()
    result = formalize_row(
        _row(), tmp_path, verifier, source_at=source_at, expected_project="llvm"
    )

    assert result.status == "accepted"
    assert isinstance(result.record, Record)
    record = result.record
    assert record.provenance.origin is Origin.REAL
    assert record.split is Split.EVAL
    assert record.erroneous_src == BUGGY
    assert record.corrected_src == CORRECTED
    assert record.primary_diagnostic == _diag()
    assert record.provenance.source == "llvm:clang/lib/Foo.cpp"
    assert record.provenance.detail["predecessor_sha"] == "pred123"
    assert record.provenance.detail["fix_sha"] == "fix456"
    assert record.provenance.detail["compile_cmd"] == COMPILE_CMD
    assert record.provenance.detail["revalidated"] is True
    assert source_calls == [(tmp_path, "fix456", "clang/lib/Foo.cpp")]
    assert [call[0] for call in verifier.call_log] == [CORRECTED, BUGGY]


def test_formalize_rejects_test_support_before_reading_git(tmp_path: Path) -> None:
    source_called = False

    def source_at(checkout: Path, revision: str, path: str):
        nonlocal source_called
        source_called = True
        return CORRECTED, ""

    result = formalize_row(
        _row(source_file="llvm/tools/llvm-cov/TestingSupport.cpp"),
        tmp_path,
        _good_verifier(),
        source_at=source_at,
        expected_project="llvm",
    )

    assert result == FormalizeResult(
        status="test_source", detail="llvm/tools/llvm-cov/TestingSupport.cpp"
    )
    assert not source_called


@pytest.mark.parametrize(
    ("source_at", "verifier", "expected_status"),
    [
        (
            lambda checkout, revision, path: (None, "git object is unavailable"),
            _good_verifier(),
            "fixed_source_unavailable",
        ),
        (
            lambda checkout, revision, path: (CORRECTED, ""),
            MockVerifier(lambda source, cmd, path: _failure()),
            "corrected_not_clean",
        ),
        (
            lambda checkout, revision, path: (CORRECTED, ""),
            MockVerifier(lambda source, cmd, path: ok_result()),
            "buggy_became_clean",
        ),
        (
            lambda checkout, revision, path: (CORRECTED, ""),
            MockVerifier(
                lambda source, cmd, path: ok_result()
                if source == CORRECTED
                else _failure("err_different", 999)
            ),
            "diagnostic_drift",
        ),
    ],
)
def test_formalize_reports_release_gate_rejections(
    tmp_path: Path, source_at, verifier, expected_status: str
) -> None:
    result = formalize_row(
        _row(), tmp_path, verifier, source_at=source_at, expected_project="llvm"
    )
    assert result.status == expected_status
    assert result.record is None
    assert result.detail


def test_cli_streams_records_and_rejections_with_manifest(
    tmp_path: Path, capsys
) -> None:
    input_path = tmp_path / "legacy.jsonl"
    with input_path.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(_row()) + "\n")
        stream.write(json.dumps(_row(
            instance_id="test-row",
            source_file="clang/test/Sema/failure.cpp",
        )) + "\n")
        stream.write("not-json\n")

    records = tmp_path / "formal" / "records.jsonl"
    rejected = tmp_path / "formal" / "rejected.jsonl"
    manifest = tmp_path / "formal" / "manifest.json"
    rc = main(
        [
            "--input", str(input_path),
            "--project", "llvm",
            "--project-checkout", str(tmp_path),
            "--clang-bin", "/fake/clang",
            "--diagtool-bin", "/fake/diagtool",
            "--out", str(records),
            "--rejected-out", str(rejected),
            "--manifest-out", str(manifest),
        ],
        verifier_factory=lambda clang, diagtool, timeout: _good_verifier(),
        source_at=lambda checkout, revision, path: (CORRECTED, ""),
    )

    assert rc == 0
    canonical = Record.from_dict(json.loads(records.read_text(encoding="utf-8")))
    assert canonical.provenance.origin is Origin.REAL
    rejected_rows = [json.loads(line) for line in rejected.read_text().splitlines()]
    assert [row["status"] for row in rejected_rows] == ["test_source", "invalid_json"]
    report = json.loads(manifest.read_text(encoding="utf-8"))
    assert report["counts"] == {
        "accepted": 1,
        "input_rows": 3,
        "rejected": 2,
        "statuses": {"accepted": 1, "invalid_json": 1, "test_source": 1},
    }
    assert report["release_gates"]["test_sources_excluded"] is True
    assert json.loads(capsys.readouterr().out) == report


def _run_cli(tmp_path: Path, rows: list[dict], jobs: int, tag: str) -> dict[str, str]:
    """Run the CLI over `rows` at a given worker count; return output text."""
    input_path = tmp_path / f"in-{tag}.jsonl"
    input_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    out = tmp_path / tag
    argv = [
        "--input", str(input_path),
        "--project", "llvm",
        "--project-checkout", str(tmp_path),
        "--clang-bin", "/fake/clang",
        "--diagtool-bin", "/fake/diagtool",
        "--out", str(out / "records.jsonl"),
        "--rejected-out", str(out / "rejected.jsonl"),
        "--manifest-out", str(out / "manifest.json"),
        "--jobs", str(jobs),
    ]
    assert main(
        argv,
        verifier_factory=lambda clang, diagtool, timeout: _good_verifier(),
        source_at=lambda checkout, revision, path: (CORRECTED, ""),
    ) == 0
    manifest = json.loads((out / "manifest.json").read_text())
    manifest.pop("input", None)
    manifest["outputs"] = {}
    return {
        "records": (out / "records.jsonl").read_text(),
        "rejected": (out / "rejected.jsonl").read_text(),
        "manifest": json.dumps(manifest, sort_keys=True),
    }


def test_worker_count_does_not_change_the_output(tmp_path: Path) -> None:
    # Each row costs two large-TU compiles, so the real run must parallelise.
    # Parallelism is only safe if it is invisible: same records, same order,
    # same rejection lines, same counts.
    rows = [_row(instance_id=f"row-{n}", commit_sha=f"pred{n}") for n in range(6)]
    rows.insert(3, _row(instance_id="test-row",
                        source_file="clang/test/Sema/failure.cpp"))

    serial = _run_cli(tmp_path, rows, jobs=1, tag="serial")
    parallel = _run_cli(tmp_path, rows, jobs=4, tag="parallel")

    assert parallel == serial
    assert len(serial["records"].splitlines()) == 6


def test_worker_count_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        _run_cli(tmp_path, [_row()], jobs=0, tag="zero")
