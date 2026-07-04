"""Tests for scope classification (strict C/C++ vs non-C/C++ dialect/target)."""
from __future__ import annotations

from gen.scope import (build_scope_prompt, is_obviously_out_of_scope,
                       parse_scope_verdicts)


def test_keyword_catches_obvious_non_cxx_dialects():
    for n in ("err_omp_no_dsa", "err_acc_construct", "err_opencl_x", "err_hlsl_y",
              "err_cuda_kernel", "err_objc_property", "err_sycl_z",
              "err_arc_may_not", "warn_dllimport_x", "err_sve_bad"):
        assert is_obviously_out_of_scope(n), n


def test_keyword_leaves_plain_cxx_alone():
    for n in ("err_expected_semi_declaration", "err_typecheck_invalid_operands",
              "err_template_arg_list_different_arity", "err_constexpr_dtor"):
        assert not is_obviously_out_of_scope(n), n


def test_parse_scope_verdicts_reads_in_out_lines():
    reply = "1: IN\n2: OUT\n3 : in\n4) OUT"
    v = parse_scope_verdicts(reply, 4)
    assert v == {0: True, 1: False, 2: True, 3: False}


def test_parse_scope_verdicts_ignores_out_of_range_and_junk():
    v = parse_scope_verdicts("blah\n1: IN\n9: OUT\nnope", 2)
    assert v == {0: True}


def test_build_scope_prompt_lists_numbered_items():
    msgs = build_scope_prompt([("err_a", "msg a"), ("err_b", "msg b")])
    blob = "\n".join(m["content"] for m in msgs)
    assert "1." in blob and "err_a" in blob and "err_b" in blob
    assert any(m["role"] == "system" for m in msgs)
