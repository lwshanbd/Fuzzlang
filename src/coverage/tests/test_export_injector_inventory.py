from __future__ import annotations

import csv
import json
import sys

from coverage import export_injector_inventory as inventory
from gen.fuzzlang_dsl.injector import FuzzLangInjector


def test_export_inventory_writes_mapping_and_uncovered_rows(tmp_path, monkeypatch):
    catalog_dir = tmp_path / "Basic"
    catalog_dir.mkdir()
    (catalog_dir / "DiagnosticSemaKinds.td").write_text(
        'def err_a : Error<"a">;\n'
        'def err_b : Error<"b">;\n'
    )
    injectors = tmp_path / "injectors.jsonl"
    injectors.write_text("".join(
        injector.to_json() + "\n"
        for injector in (
            FuzzLangInjector.append_fragment(
                target_diag="err_a", language="c++", fragment="bad_a;"
            ),
            FuzzLangInjector.append_fragment(
                target_diag="err_c", language="c", fragment="bad_c;"
            ),
        )
    ))
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps({
        "inputs": {"injector_files": [str(injectors)]},
        "verified_diagnostic_names": ["err_a"],
        "counts": {"catalog_error_diagnostic_total": 2},
    }))
    test_reachable = tmp_path / "test-reachable.txt"
    test_reachable.write_text("err_a\nerr_b\n")
    injector_out = tmp_path / "injectors.csv"
    diagnostic_out = tmp_path / "diagnostics.csv"
    uncovered_out = tmp_path / "uncovered.csv"
    summary_out = tmp_path / "summary.csv"

    monkeypatch.setattr(sys, "argv", [
        "export_injector_inventory.py",
        "--audit", str(audit),
        "--catalog-dir", str(catalog_dir),
        "--test-reachable", str(test_reachable),
        "--injector-out", str(injector_out),
        "--diagnostic-out", str(diagnostic_out),
        "--uncovered-out", str(uncovered_out),
        "--summary-out", str(summary_out),
    ])

    assert inventory.main() == 0
    injector_rows = list(csv.DictReader(injector_out.open()))
    assert [(row["diagnostic_name"], row["strict_diagnostic_covered"])
            for row in injector_rows] == [
                ("err_a", "true"),
                ("err_c", "false"),
            ]
    diagnostic_rows = list(csv.DictReader(diagnostic_out.open()))
    assert diagnostic_rows == [
        {
            "diagnostic_name": "err_a",
            "diagnostic_id": "",
            "component": "Sema",
            "portable_injector_count": "1",
            "languages": "c++",
            "operations": "append",
            "target_is_catalog_error": "true",
            "strict_diagnostic_covered": "true",
        },
        {
            "diagnostic_name": "err_c",
            "diagnostic_id": "",
            "component": "",
            "portable_injector_count": "1",
            "languages": "c",
            "operations": "append",
            "target_is_catalog_error": "false",
            "strict_diagnostic_covered": "false",
        },
    ]
    uncovered_rows = list(csv.DictReader(uncovered_out.open()))
    assert uncovered_rows == [{
        "diagnostic_name": "err_b",
        "component": "Sema",
        "tablegen_message": "b",
        "test_reachable": "true",
        "emission_context_available": "false",
    }]
    summary = {row["metric"]: row["value"]
               for row in csv.DictReader(summary_out.open())}
    assert summary["strict_verified_diagnostic_types"] == "1"
    assert summary["injector_target_diagnostic_types"] == "2"
    assert summary["injector_targets_not_strictly_verified"] == "1"
    assert summary["uncovered_catalog_error_types"] == "1"
    assert summary["test_reachable_strict_overlap"] == "1"
    assert summary["strict_fuzzlang_only_types"] == "0"
    assert summary["test_reachable_uncovered_types"] == "1"
