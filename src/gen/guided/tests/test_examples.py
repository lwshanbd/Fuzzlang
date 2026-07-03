"""Tests for mining example snippets per diagnostic from a corpus."""
from foundation.types import DiagInfo, VerifierResult
from foundation.verifier.base import PLACEHOLDER
from foundation.verifier.mock import MockVerifier, ok_result
from gen.guided.examples import feature_configs, mine, mine_examples, sweep_configs


def _err(name):
    d = DiagInfo(diag_id=1, diag_name=name, diag_msg="m", file="f", line=1, col=1,
                 start_byte=0, end_byte=1, span_snippet="x")
    return VerifierResult(ok=False, diag=d, raw_stderr="error")


def test_groups_snippets_by_diagnostic():
    def policy(s, c, l):
        if s.startswith("A"):
            return _err("err_a")
        if s == "B":
            return _err("err_b")
        return ok_result()
    idx = mine_examples([("A1", "s1"), ("B", "s2"), ("A2", "s3")], MockVerifier(policy))
    assert idx == {"err_a": ["A1", "A2"], "err_b": ["B"]}


def test_skips_clean_and_unnamed():
    noname = VerifierResult(
        ok=False,
        diag=DiagInfo(diag_id=None, diag_name=None, diag_msg="m", file="f", line=1,
                      col=1, start_byte=0, end_byte=1, span_snippet="x"),
        raw_stderr="error")

    def policy(s, c, l):
        if s == "clean":
            return ok_result()
        if s == "noname":
            return noname
        return _err("err_x")
    idx = mine_examples([("clean", "1"), ("noname", "2"), ("bad", "3")], MockVerifier(policy))
    assert idx == {"err_x": ["bad"]}


def test_max_per_diag_caps_examples():
    idx = mine_examples([("x1", "a"), ("x2", "b"), ("x3", "c")],
                        MockVerifier(lambda s, c, l: _err("err_x")), max_per_diag=2)
    assert idx == {"err_x": ["x1", "x2"]}


# ---- multi-config sweep (breadth) -------------------------------------------

def _cfg_policy(s, cmd, l):
    """Different configs trigger different diagnostics for the same source."""
    flat = " ".join(cmd)
    if "c89" in flat:
        return _err("err_c89_only")
    if "c++2b" in flat:
        return _err("err_cxx2b_only")
    return ok_result()


def test_sweep_unions_diagnostics_across_configs():
    cfgs = [["clang", "-std=c89", PLACEHOLDER], ["clang", "-std=c++2b", PLACEHOLDER]]
    idx = mine_examples([("S", "s1")], MockVerifier(_cfg_policy), compile_cmds=cfgs)
    assert idx == {"err_c89_only": ["S"], "err_cxx2b_only": ["S"]}


def test_sweep_same_diag_across_configs_kept_once():
    cfgs = [["a", PLACEHOLDER], ["b", PLACEHOLDER]]
    idx = mine_examples([("S", "s1")], MockVerifier(lambda s, c, l: _err("err_x")),
                        compile_cmds=cfgs)
    assert idx == {"err_x": ["S"]}


def test_parallel_workers_match_sequential():
    def policy(s, c, l):
        return ok_result() if s == "clean" else _err("err_" + s)
    src = [(f"S{i}", f"id{i}") for i in range(25)] + [("clean", "idc")]
    seq = mine_examples(src, MockVerifier(policy))
    par = mine_examples(src, MockVerifier(policy), workers=4)
    assert seq == par


def test_per_source_cmds_add_configs_for_that_source_only():
    def policy(s, cmd, l):
        return _err("err_special") if "SPECIAL" in " ".join(cmd) else ok_result()

    def per_source(snippet, sid):
        return [["clang", "SPECIAL", PLACEHOLDER]] if sid == "s1" else []

    idx = mine_examples([("A", "s1"), ("B", "s2")], MockVerifier(policy),
                        compile_cmds=[["clang", "base", PLACEHOLDER]],
                        per_source_cmds=per_source)
    assert idx == {"err_special": ["A"]}   # only s1 got the SPECIAL config


def test_mine_tracks_the_config_that_triggered_each_diagnostic():
    def policy(s, cmd, l):
        return _err("err_x") if "c89" in " ".join(cmd) else ok_result()
    cfgs = [["clang", "c99", PLACEHOLDER], ["clang", "c89", PLACEHOLDER]]
    examples, configs = mine([("S", "s1")], MockVerifier(policy), compile_cmds=cfgs)
    assert examples == {"err_x": ["S"]}
    assert configs["err_x"] == [["clang", "c89", PLACEHOLDER]]  # the winning config


def test_feature_configs_cover_major_feature_flags_and_use_placeholders():
    cfgs = feature_configs("/RES")
    flat = " ".join(t for cfg in cfgs for t in cfg)
    for needed in ("-fopenmp", "-fobjc-arc", "hlsl", "-fblocks", "-fmodules",
                   "-target-feature"):
        assert needed in flat, needed
    assert all(cfg[0] == "__CLANG__" and cfg[-1] == PLACEHOLDER for cfg in cfgs)
    # cc1 target-feature configs must carry the resource dir.
    assert any("-cc1" in cfg and "/RES" in cfg for cfg in cfgs)


def test_sweep_configs_cover_c_cxx_objc_and_use_placeholders():
    cfgs = sweep_configs()
    flat = " ".join(t for cfg in cfgs for t in cfg)
    assert "c++" in flat and "objective-c" in flat and "-std=c" in flat
    assert all(cfg[0] == "__CLANG__" and cfg[-1] == PLACEHOLDER for cfg in cfgs)
