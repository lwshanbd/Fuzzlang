"""Tests for parsing %clang_cc1 RUN-line flags out of Clang test files.

clang/test files carry the exact frontend flags each diagnostic needs
(`-triple`, `-target-feature`, `-fopenmp`, `-x <lang>`, `-std=...`). Replaying
those as `clang -cc1 ... -fsyntax-only` triggers diagnostics the language-only
sweep never reaches (target-feature, OpenMP, etc.).
"""
from __future__ import annotations

from foundation.verifier.base import PLACEHOLDER
from gen.guided.runline import (
    parse_analyzer_configs,
    parse_cc1_configs,
    parse_cl_configs,
    parse_driver_configs,
)

RES = "/RES"


def _one(text):
    cfgs = parse_cc1_configs(text, resource_dir=RES)
    assert len(cfgs) == 1, cfgs
    return cfgs[0]


def test_basic_cc1_line_keeps_triple_forces_syntax_only():
    cfg = _one("// RUN: %clang_cc1 -triple aarch64 -verify -fsyntax-only %s\n")
    assert cfg[0] == "__CLANG__" and cfg[1] == "-cc1"
    assert cfg[-1] == PLACEHOLDER
    assert "-resource-dir" in cfg and RES in cfg
    assert "-triple" in cfg and "aarch64" in cfg
    assert "-verify" not in cfg          # -verify stripped
    assert "%s" not in cfg               # source token stripped
    assert cfg.count("-fsyntax-only") == 1   # forced once, not duplicated


def test_non_cc1_run_line_is_ignored():
    # A driver-mode RUN line (no %clang_cc1) yields no cc1 config.
    assert parse_cc1_configs("// RUN: %clang -O2 %s -o %t\n", resource_dir=RES) == []


def test_pipe_and_output_and_actions_stripped():
    cfg = _one("// RUN: %clang_cc1 -emit-llvm -o - %s | FileCheck %s\n")
    assert "FileCheck" not in cfg and "-emit-llvm" not in cfg
    assert "-o" not in cfg and "-" not in cfg


def test_line_continuation_is_joined():
    text = ("// RUN: %clang_cc1 -triple aarch64 -target-feature +sme \\\n"
            "// RUN:   -fsyntax-only -verify %s\n")
    cfg = _one(text)
    assert "-target-feature" in cfg and "+sme" in cfg
    assert "-triple" in cfg and "aarch64" in cfg


def test_lit_substitution_tokens_dropped():
    cfg = _one("// RUN: %clang_cc1 -x c -std=c11 -I %S/Inputs %t %s -fsyntax-only\n")
    assert "-x" in cfg and "c" in cfg and "-std=c11" in cfg
    assert not any(tok.startswith("%") for tok in cfg)   # %S, %t gone


def test_multiple_run_lines_give_multiple_configs():
    text = ("// RUN: %clang_cc1 -triple x86_64-linux -fsyntax-only -verify %s\n"
            "// RUN: %clang_cc1 -triple aarch64 -fopenmp -fsyntax-only -verify %s\n")
    cfgs = parse_cc1_configs(text, resource_dir=RES)
    assert len(cfgs) == 2
    joined = [" ".join(c) for c in cfgs]
    assert any("x86_64-linux" in j for j in joined)
    assert any("aarch64" in j and "-fopenmp" in j for j in joined)


def test_identical_run_lines_deduped():
    text = ("// RUN: %clang_cc1 -triple aarch64 -fsyntax-only -verify %s\n"
            "// RUN: %clang_cc1 -triple aarch64 -fsyntax-only -verify %s\n")
    assert len(parse_cc1_configs(text, resource_dir=RES)) == 1


def test_driver_line_keeps_frontend_flags_and_forces_syntax_only():
    cfgs = parse_driver_configs(
        "// RUN: not %clang -fblocks -fbracket-depth=512 -fsyntax-only %s 2>&1\n"
    )
    assert cfgs == [["__CLANG__", "-fblocks", "-fbracket-depth=512",
                     "-fsyntax-only", PLACEHOLDER]]


def test_analyzer_line_preserves_analyze_action():
    cfgs = parse_analyzer_configs(
        "// RUN: %clang_analyze_cc1 -std=c11 -analyzer-checker=core -verify %s\n",
        resource_dir=RES,
    )
    assert cfgs == [["__CLANG__", "-cc1", "-resource-dir", RES, "-std=c11",
                     "-analyzer-checker=core", "-analyze", PLACEHOLDER]]


def test_cl_line_uses_cl_driver_mode_and_syntax_check():
    cfgs = parse_cl_configs("// RUN: not %clang_cl /std:c++20 /c %s 2>&1\n")
    assert cfgs == [["__CLANG__", "--driver-mode=cl", "/std:c++20", "/Zs",
                     PLACEHOLDER]]
