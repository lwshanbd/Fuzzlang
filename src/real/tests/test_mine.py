"""Tests for extracting a real-error Record from PR/issue/commit text."""
from foundation.diagnostics.catalog import Catalog, DiagEntry
from foundation.diagnostics.matcher import DiagnosticMatcher
from foundation.record import Origin, Split
from real.mine import extract_from_text, parse_extract

_MATCHER = DiagnosticMatcher(Catalog([
    DiagEntry(name="err_undeclared_var_use", severity="Error",
              message="use of undeclared identifier %0", component="Sema"),
]))

GOOD_JSON = (
    '{"is_compile_error": true, '
    '"error_message": "use of undeclared identifier \'foo\'", '
    '"broken_code": "int main(){ return foo; }", '
    '"fixed_code": "int main(){ int foo=0; return foo; }"}'
)


def _chat(reply):
    return lambda messages: reply


def test_parse_extract_reads_json_even_with_prose():
    d = parse_extract("Sure, here:\n" + GOOD_JSON + "\nhope that helps")
    assert d["is_compile_error"] is True
    assert d["broken_code"].startswith("int main")


def test_extract_emits_real_record_with_matched_diagnostic():
    rec = extract_from_text("<pr text>", _chat(GOOD_JSON), matcher=_MATCHER,
                            project="llvm/llvm-project", ref="pr/123",
                            url="https://github.com/llvm/llvm-project/pull/123")
    assert rec is not None
    assert rec.provenance.origin is Origin.REAL
    assert rec.split is Split.EVAL
    assert rec.corrected_src.startswith("int main(){ int foo")
    assert "return foo" in rec.erroneous_src
    assert rec.primary_diagnostic.diag_name == "err_undeclared_var_use"
    assert "llvm/llvm-project" in rec.provenance.source


def test_extract_none_when_not_a_compile_error():
    reply = '{"is_compile_error": false, "error_message": "", "broken_code": "", "fixed_code": ""}'
    assert extract_from_text("x", _chat(reply), matcher=_MATCHER,
                             project="p", ref="r", url="u") is None


def test_extract_none_when_no_fix():
    reply = ('{"is_compile_error": true, "error_message": "use of undeclared identifier \'x\'", '
             '"broken_code": "int m(){return x;}", "fixed_code": ""}')
    assert extract_from_text("x", _chat(reply), matcher=_MATCHER,
                             project="p", ref="r", url="u") is None


def test_extract_keeps_real_error_even_if_matcher_finds_no_name():
    reply = ('{"is_compile_error": true, "error_message": "some brand new message not in catalog", '
             '"broken_code": "bad", "fixed_code": "good"}')
    rec = extract_from_text("x", _chat(reply), matcher=_MATCHER, project="p", ref="r", url="u")
    assert rec is not None
    assert rec.primary_diagnostic.diag_name is None   # unnamed, but still real Column-B data
