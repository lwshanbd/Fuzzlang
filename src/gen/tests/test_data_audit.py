from __future__ import annotations

import json
from pathlib import Path

from gen.data_audit import TIER_NAMES, audit_tiers
from gen.run_data_audit import main


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row) + "\n")


def _canonical(
    record_id: str,
    *,
    source: str,
    source_path: str,
    diagnostic: str,
    corrected_src: str | None = "int main() {}",
) -> dict:
    return {
        "record_id": record_id,
        "erroneous_src": "int main( {}",
        "corrected_src": corrected_src,
        "diagnostics": [{"diag_name": diagnostic}],
        "provenance": {
            "origin": "mutate",
            "source": source,
            "detail": {"source_path": source_path},
        },
        "split": "eval",
        "language": "c++",
    }


def test_audit_tiers_counts_pairs_diagnostics_overlap_and_strict_test_paths(
    tmp_path: Path,
) -> None:
    breadth = tmp_path / "breadth.jsonl"
    breadth_extra = tmp_path / "breadth-extra.jsonl"
    real_source = tmp_path / "real-source.jsonl"
    naterr = tmp_path / "naterr.jsonl"

    _write_jsonl(
        breadth,
        [
            _canonical(
                "b1",
                source="llvm:clang/lib/Sema/Sema.cpp",
                source_path="clang/lib/Sema/Sema.cpp",
                diagnostic="err_a",
            ),
            _canonical(
                "b2",
                source="llvm:llvm/tools/llvm-cov/TestingSupport.cpp",
                source_path="llvm/tools/llvm-cov/TestingSupport.cpp",
                diagnostic="err_b",
                corrected_src=None,
            ),
        ],
    )
    _write_jsonl(
        real_source,
        [
            _canonical(
                "r1",
                source="llvm:clang/lib/Sema/Sema.cpp",
                source_path="clang/lib/Sema/Sema.cpp",
                diagnostic="err_b",
            )
        ],
    )
    _write_jsonl(
        breadth_extra,
        [
            _canonical(
                "b3",
                source="llvm:clang/lib/Sema/Sema.cpp",
                source_path="clang/lib/Sema/Sema.cpp",
                diagnostic="err_a",
            )
        ],
    )
    _write_jsonl(
        naterr,
        [
            {
                "instance_id": "n1",
                "project": "llvm",
                "source_file": "llvm/lib/IR/Verifier.cpp",
                "buggy_src": "void f( {}",
                "diag_name": "err_c",
            }
        ],
    )

    report = audit_tiers(
        {
            "breadth": [breadth, breadth_extra],
            "real_source": [real_source],
            "naterr": [naterr],
        }
    )

    assert tuple(report["tiers"]) == TIER_NAMES
    assert report["tiers"]["breadth"] == {
        "input_files": [str(breadth), str(breadth_extra)],
        "records": 3,
        "paired_records": 2,
        "missing_corrected_src": 1,
        "missing_erroneous_src": 0,
        "distinct_diagnostics": 2,
        "diagnostic_names": ["err_a", "err_b"],
        "unique_sources": 2,
        "missing_source": 0,
        "test_sources": 1,
        "test_source_paths": ["llvm/tools/llvm-cov/TestingSupport.cpp"],
        "schema_counts": {"canonical_record": 3},
        "invalid_json_rows": 0,
        "non_object_rows": 0,
    }
    assert report["tiers"]["real_source"]["paired_records"] == 1
    assert report["tiers"]["naterr"]["paired_records"] == 0
    assert report["tiers"]["naterr"]["missing_corrected_src"] == 1
    assert report["tiers"]["naterr"]["schema_counts"] == {"legacy_naterr": 1}

    overlap = report["source_overlap"]
    assert overlap["breadth__real_source"] == {
        "count": 1,
        "sources": ["llvm:clang/lib/Sema/Sema.cpp"],
    }
    assert overlap["breadth__naterr"]["count"] == 0
    assert overlap["real_source__naterr"]["count"] == 0
    assert report["within_tier_source_overlap"]["breadth"] == {
        "count": 1,
        "sources": ["llvm:clang/lib/Sema/Sema.cpp"],
    }
    assert report["within_tier_source_overlap"]["real_source"]["count"] == 0


def test_cli_streams_jsonl_and_writes_machine_readable_report(
    tmp_path: Path, capsys
) -> None:
    inputs = {}
    for tier in TIER_NAMES:
        path = tmp_path / f"{tier}.jsonl"
        _write_jsonl(
            path,
            [
                _canonical(
                    tier,
                    source=f"project:src/{tier}.cc",
                    source_path=f"src/{tier}.cc",
                    diagnostic=f"err_{tier}",
                )
            ],
        )
        inputs[tier] = path

    # Invalid rows are reported rather than preventing the rest of a large
    # stream from being audited.
    with inputs["naterr"].open("a", encoding="utf-8") as stream:
        stream.write("not-json\n")
        stream.write("[]\n")

    output = tmp_path / "audit.json"
    assert main(
        [
            "--breadth",
            str(inputs["breadth"]),
            "--real-source",
            str(inputs["real_source"]),
            "--naterr",
            str(inputs["naterr"]),
            "--out",
            str(output),
        ]
    ) == 0

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schema_version"] == 1
    assert report["tiers"]["naterr"]["records"] == 1
    assert report["tiers"]["naterr"]["invalid_json_rows"] == 1
    assert report["tiers"]["naterr"]["non_object_rows"] == 1
    assert json.loads(capsys.readouterr().out) == report
