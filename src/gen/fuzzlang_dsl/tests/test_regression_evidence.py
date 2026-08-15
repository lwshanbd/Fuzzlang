from __future__ import annotations

from gen.fuzzlang_dsl.regression_evidence import (
    has_regression_test_source_evidence, has_regression_trigger_evidence,
    regression_evidence_for,
)
from gen.fuzzlang_dsl import regression_evidence


def test_regression_evidence_uses_a_test_only_as_compiler_trigger_context(
    tmp_path,
):
    tests = tmp_path / "clang-test"
    tests.mkdir()
    sample = tests / "deduction.cpp"
    sample.write_text(
        "template<class T> struct Box;\n"
        "template<class T> Box(T) -> Box<T>;\n"
        "auto value = Box(1); // expected-error {{has no definition and no}}\n"
    )

    evidence = regression_evidence_for(
        "template %0 has no definition and no %select{|viable }1deduction guides",
        tests,
    )

    assert evidence is not None
    assert "deduction.cpp" in evidence
    assert "expected-error" in evidence
    assert "template<class T> struct Box" in evidence


def test_regression_evidence_returns_none_when_no_literal_trigger_hint_exists(
    tmp_path,
):
    tests = tmp_path / "clang-test"
    tests.mkdir()
    (tests / "unrelated.cpp").write_text("int main() {}\n")

    assert regression_evidence_for("%0 %1", tests) is None


def test_regression_evidence_treats_a_search_timeout_as_optional_missing_context(
    tmp_path, monkeypatch,
):
    tests = tmp_path / "clang-test"
    tests.mkdir()

    def _timeout(*args, **kwargs):
        raise regression_evidence.subprocess.TimeoutExpired(["rg"], 30)

    monkeypatch.setattr(regression_evidence.subprocess, "run", _timeout)

    assert regression_evidence_for(
        "this diagnostic message is long enough", tests,
    ) is None


def test_regression_evidence_bounds_optional_search_latency(tmp_path, monkeypatch):
    tests = tmp_path / "clang-test"
    tests.mkdir()
    captured = []

    def _search(*args, **kwargs):
        captured.append(kwargs["timeout"])
        return regression_evidence.subprocess.CompletedProcess(args[0], 1, "")

    monkeypatch.setattr(regression_evidence.subprocess, "run", _search)

    assert regression_evidence_for(
        "this diagnostic message is long enough", tests,
    ) is None
    assert captured == [5]


def test_exact_test_trigger_configuration_counts_as_existing_evidence():
    assert has_regression_trigger_evidence(
        "Clang regression-test trigger evidence (not a dataset source):\n"
        "  -fsyntax-only -x c++ -std=c++2b"
    )
    assert not has_regression_test_source_evidence(
        "Clang regression-test trigger evidence (not a dataset source):\n"
        "  -fsyntax-only -x c++ -std=c++2b"
    )


def test_test_source_evidence_requires_an_excerpt_not_only_a_scan_configuration():
    assert has_regression_test_source_evidence(
        "Regression-test trigger evidence (not a dataset source):\n"
        "SemaCXX/example.cpp:\nint x = ; // expected-error {{expected expression}}"
    )
