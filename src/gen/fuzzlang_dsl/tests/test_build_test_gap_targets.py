from __future__ import annotations

import json

from foundation.diagnostics.catalog import Catalog, DiagEntry
from gen.fuzzlang_dsl import build_test_gap_targets


def test_build_test_gap_targets_subtracts_strictly_covered_and_records_manifest(
    tmp_path,
):
    first = tmp_path / "first.txt"
    first.write_text("err_b\nerr_a\n")
    second = tmp_path / "second.txt"
    second.write_text("err_c\nerr_a\n")
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps({"verified_diagnostic_names": ["err_a"]}))
    out = tmp_path / "gap.txt"
    manifest = tmp_path / "manifest.json"

    assert build_test_gap_targets.main([
        "--test-reachable", str(first),
        "--test-reachable", str(second),
        "--strict-audit", str(audit),
        "--out", str(out),
        "--manifest-out", str(manifest),
    ]) == 0

    assert out.read_text() == "err_b\nerr_c\n"
    metadata = json.loads(manifest.read_text())
    assert metadata["test_reachable_diagnostic_types"] == 3
    assert metadata["strictly_covered_diagnostic_types"] == 1
    assert metadata["test_reachable_uncovered_diagnostic_types"] == 2
    assert metadata["diagnostic_names_sha256"]


def test_build_test_gap_targets_applies_offset_and_limit(tmp_path):
    tests = tmp_path / "tests.txt"
    tests.write_text("err_a\nerr_b\nerr_c\n")
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps({"verified_diagnostic_names": []}))
    out = tmp_path / "gap.txt"

    assert build_test_gap_targets.main([
        "--test-reachable", str(tests),
        "--strict-audit", str(audit),
        "--offset", "1",
        "--limit", "1",
        "--out", str(out),
    ]) == 0

    assert out.read_text() == "err_b\n"


def test_catalog_error_filter_drops_test_reachable_warnings_and_extensions():
    catalog = Catalog([
        DiagEntry("err_core", "Error", "core error", "Sema"),
        DiagEntry("warn_only", "Warning", "warning", "Sema"),
        DiagEntry("ext_only", "Extension", "extension", "Sema"),
    ])

    assert build_test_gap_targets.catalog_error_names(
        ["warn_only", "err_core", "unknown", "ext_only"], catalog,
    ) == ["err_core"]


def test_build_test_gap_targets_can_route_an_ordinary_cpp23_slice(tmp_path):
    tests = tmp_path / "tests.txt"
    tests.write_text(
        "err_acc_invalid_directive\n"
        "err_concept_no_type_named\n"
        "err_attribute_pointers_only\n"
    )
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps({"verified_diagnostic_names": []}))
    out = tmp_path / "gap.txt"

    assert build_test_gap_targets.main([
        "--test-reachable", str(tests),
        "--strict-audit", str(audit),
        "--language", "c++",
        "--cpp-standard", "c++23",
        "--out", str(out),
    ]) == 0

    assert out.read_text() == (
        "err_attribute_pointers_only\n"
        "err_concept_no_type_named\n"
    )


def test_build_test_gap_targets_can_require_a_plain_test_trigger_mode(tmp_path):
    tests = tmp_path / "tests.txt"
    tests.write_text("err_a\nerr_b\n")
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps({"verified_diagnostic_names": []}))
    scan = tmp_path / "scan.json"
    scan.write_text(json.dumps({
        "trigger_configs": {
            "err_a": [[
                "__CLANG__", "-x", "c++", "-std=c++2b", "-fsyntax-only",
                "__SRC__",
            ]],
            "err_b": [[
                "__CLANG__", "-cc1", "-triple", "aarch64", "-fsyntax-only",
                "__SRC__",
            ]],
        },
    }))
    out = tmp_path / "gap.txt"

    assert build_test_gap_targets.main([
        "--test-reachable", str(tests),
        "--strict-audit", str(audit),
        "--trigger-config", str(scan),
        "--plain-driver-language", "c++",
        "--plain-driver-standard", "c++23",
        "--out", str(out),
    ]) == 0

    assert out.read_text() == "err_a\n"


def test_build_test_gap_targets_can_route_a_plain_cpp11_trigger(tmp_path):
    tests = tmp_path / "tests.txt"
    tests.write_text("err_legacy\n")
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps({"verified_diagnostic_names": []}))
    scan = tmp_path / "scan.json"
    scan.write_text(json.dumps({
        "trigger_configs": {
            "err_legacy": [[
                "__CLANG__", "-x", "c++", "-std=c++11", "-fsyntax-only",
                "__SRC__",
            ]],
        },
    }))
    out = tmp_path / "gap.txt"

    assert build_test_gap_targets.main([
        "--test-reachable", str(tests),
        "--strict-audit", str(audit),
        "--language", "c++",
        "--cpp-standard", "c++11",
        "--trigger-config", str(scan),
        "--plain-driver-language", "c++",
        "--plain-driver-standard", "c++11",
        "--out", str(out),
    ]) == 0

    assert out.read_text() == "err_legacy\n"


def test_build_test_gap_targets_can_route_a_plain_cpp2c_trigger(tmp_path):
    tests = tmp_path / "tests.txt"
    tests.write_text("err_cpp26\n")
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps({"verified_diagnostic_names": []}))
    scan = tmp_path / "scan.json"
    scan.write_text(json.dumps({
        "trigger_configs": {
            "err_cpp26": [[
                "__CLANG__", "-x", "c++", "-std=c++26", "-fsyntax-only",
                "__SRC__",
            ]],
        },
    }))
    out = tmp_path / "gap.txt"

    assert build_test_gap_targets.main([
        "--test-reachable", str(tests),
        "--strict-audit", str(audit),
        "--language", "c++",
        "--cpp-standard", "c++2c",
        "--trigger-config", str(scan),
        "--plain-driver-language", "c++",
        "--plain-driver-standard", "c++2c",
        "--out", str(out),
    ]) == 0

    assert out.read_text() == "err_cpp26\n"


def test_build_test_gap_targets_can_route_a_cc1_standard_only_trigger(tmp_path):
    tests = tmp_path / "tests.txt"
    tests.write_text("err_cpp26\nerr_target_only\n")
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps({"verified_diagnostic_names": []}))
    scan = tmp_path / "scan.json"
    scan.write_text(json.dumps({
        "trigger_configs": {
            "err_cpp26": [[
                "__CLANG__", "-cc1", "-resource-dir", "/toolchain", "-std=c++2c",
                "-fsyntax-only", "__SRC__",
            ]],
            "err_target_only": [[
                "__CLANG__", "-cc1", "-triple", "aarch64", "-std=c++2c",
                "-fsyntax-only", "__SRC__",
            ]],
        },
    }))
    out = tmp_path / "gap.txt"

    assert build_test_gap_targets.main([
        "--test-reachable", str(tests),
        "--strict-audit", str(audit),
        "--language", "c++",
        "--cpp-standard", "c++2c",
        "--trigger-config", str(scan),
        "--standard-trigger-language", "c++",
        "--standard-trigger-standard", "c++2c",
        "--out", str(out),
    ]) == 0

    assert out.read_text() == "err_cpp26\n"


def test_build_test_gap_targets_excludes_an_inflight_target_queue(tmp_path):
    tests = tmp_path / "tests.txt"
    tests.write_text("err_a\nerr_b\n")
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps({"verified_diagnostic_names": []}))
    inflight = tmp_path / "inflight.txt"
    inflight.write_text("err_a\n")
    out = tmp_path / "gap.txt"

    assert build_test_gap_targets.main([
        "--test-reachable", str(tests),
        "--strict-audit", str(audit),
        "--exclude-name-file", str(inflight),
        "--out", str(out),
    ]) == 0

    assert out.read_text() == "err_b\n"


def test_build_test_gap_targets_can_require_test_trigger_flags(tmp_path):
    tests = tmp_path / "tests.txt"
    tests.write_text("err_openmp\nerr_plain\n")
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps({"verified_diagnostic_names": []}))
    scan = tmp_path / "scan.json"
    scan.write_text(json.dumps({
        "trigger_configs": {
            "err_openmp": [[
                "__CLANG__", "-fopenmp", "-x", "c++", "-fsyntax-only",
                "__SRC__",
            ]],
            "err_plain": [[
                "__CLANG__", "-x", "c++", "-fsyntax-only", "__SRC__",
            ]],
        },
    }))
    out = tmp_path / "gap.txt"

    assert build_test_gap_targets.main([
        "--test-reachable", str(tests),
        "--strict-audit", str(audit),
        "--trigger-config", str(scan),
        "--require-trigger-flag", "fopenmp",
        "--out", str(out),
    ]) == 0

    assert out.read_text() == "err_openmp\n"


def test_build_test_gap_targets_can_require_a_bare_objective_c_trigger(tmp_path):
    tests = tmp_path / "tests.txt"
    tests.write_text("err_objc_missing_end\nerr_objc_exceptions_disabled\n")
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps({"verified_diagnostic_names": []}))
    scan = tmp_path / "scan.json"
    scan.write_text(json.dumps({
        "trigger_configs": {
            "err_objc_missing_end": [[
                "__CLANG__", "-x", "objective-c", "-fsyntax-only", "__SRC__",
            ]],
            "err_objc_exceptions_disabled": [[
                "__CLANG__", "-x", "objective-c", "-fblocks", "-fsyntax-only",
                "__SRC__",
            ]],
        },
    }))
    out = tmp_path / "gap.txt"

    assert build_test_gap_targets.main([
        "--test-reachable", str(tests),
        "--strict-audit", str(audit),
        "--language", "objective-c",
        "--feature-mode", "objc",
        "--trigger-config", str(scan),
        "--bare-driver-language", "objective-c",
        "--out", str(out),
    ]) == 0

    assert out.read_text() == "err_objc_missing_end\n"
