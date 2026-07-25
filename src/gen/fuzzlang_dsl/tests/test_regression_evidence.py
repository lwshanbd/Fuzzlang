from __future__ import annotations

from gen.fuzzlang_dsl.regression_evidence import regression_evidence_for


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
