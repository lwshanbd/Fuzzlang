from __future__ import annotations

from foundation.types import DiagInfo, VerifierResult
from foundation.verifier.mock import MockVerifier
from gen.realcorpus.corpus import Fragment
from gen.realcorpus.run_realcorpus import drive_targets, to_run_sweep_row
from gen.realcorpus.targets import Target


def _frag(feats=frozenset(), path="clang/lib/A.cpp"):
    return Fragment(rel_path=path, tu_src="int f(){ return 0; }\n",
                    span=(0, 19), features=feats, compile_cmd=["__CLANG__", "__SRC__"])


def test_drive_targets_emits_one_record_per_success_up_to_cap():
    targets = [Target(name=f"err_{i}", message="m", features=frozenset(),
                      exemplar=None, covered=True) for i in range(3)]
    frags = [_frag()]
    diag = DiagInfo(diag_id=1, diag_name="err_0", diag_msg="m", file="clang/lib/A.cpp",
                    line=1, col=1, start_byte=0, end_byte=1, span_snippet="x")
    res = VerifierResult(ok=False, diag=diag, raw_stderr="a:1:1: error: m\n")

    def induce(target, fragment, chat, verifier, **kw):     # always succeeds
        return ("int f(){ return 0 }\n", res)

    recs = drive_targets(targets, frags, MockVerifier(lambda s, c, l: res), chat=None,
                         induce_fn=induce, candidates_per_target=2, max_instances=2)
    assert len(recs) == 2                                   # capped
    row = to_run_sweep_row(recs[0], frags[0])
    assert row["compile_cmd"] == ["__CLANG__", "__SRC__"]
    assert "cascade_size" in row
    assert row["source_path"] == "clang/lib/A.cpp"
    assert row["region_type"] == "function"


def test_drive_targets_skips_targets_that_never_induce():
    targets = [Target(name="err_x", message="m", features=frozenset(),
                      exemplar=None, covered=True)]
    recs = drive_targets(targets, [_frag()], MockVerifier(lambda s, c, l: None),
                         chat=None, induce_fn=lambda *a, **k: None,
                         candidates_per_target=2, max_instances=5)
    assert recs == []


def test_drive_targets_caps_instances_per_source_and_retries_elsewhere():
    targets = [Target(name=f"err_{i}", message="m", features=frozenset(),
                      exemplar=None, covered=True) for i in range(3)]
    frags = [_frag(path="a.cpp"), _frag(path="b.cpp")]

    def induce(target, fragment, chat, verifier, **kw):
        diag = DiagInfo(diag_id=1, diag_name=target.name, diag_msg="m",
                        file=fragment.rel_path, line=1, col=1,
                        start_byte=0, end_byte=1, span_snippet="x")
        return ("int f(){ return 0 }\n",
                VerifierResult(ok=False, diag=diag,
                               raw_stderr=f"{fragment.rel_path}:1:1: error: m\n"))

    recs = drive_targets(
        targets, frags, MockVerifier(lambda s, c, l: None), chat=None,
        induce_fn=induce, candidates_per_target=2, max_instances=3,
        max_instances_per_source=1,
    )
    assert len(recs) == 2
    assert {r.provenance.source for r in recs} == {"llvm:a.cpp", "llvm:b.cpp"}
