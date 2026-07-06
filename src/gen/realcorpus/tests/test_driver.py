from __future__ import annotations

from foundation.types import DiagInfo, VerifierResult
from foundation.verifier.mock import MockVerifier
from gen.realcorpus.corpus import Fragment
from gen.realcorpus.run_realcorpus import drive_targets, to_run_sweep_row
from gen.realcorpus.targets import Target


def _frag(feats=frozenset()):
    return Fragment(rel_path="clang/lib/A.cpp", tu_src="int f(){ return 0; }\n",
                    span=(0, 19), features=feats, compile_cmd=["__CLANG__", "__SRC__"])


def test_drive_targets_emits_one_record_per_success_up_to_cap():
    targets = [Target(name=f"err_{i}", message="m", features=frozenset(),
                      exemplar=None, covered=True) for i in range(3)]
    frags = [_frag()]
    diag = DiagInfo(diag_id=1, diag_name="err_0", diag_msg="m", file="clang/lib/A.cpp",
                    line=1, col=1, start_byte=0, end_byte=1, span_snippet="x")

    def verify(src, cmd, logical_path):
        return VerifierResult(ok=False, diag=diag, raw_stderr="a:1:1: error: m\n")

    def inject(target, fragment, chat, **kw):        # always succeeds
        return "int f(){ return 0 }\n"

    recs = drive_targets(targets, frags, MockVerifier(verify), chat=None,
                         inject_fn=inject, candidates_per_target=2, max_instances=2)
    assert len(recs) == 2                            # capped
    assert to_run_sweep_row(recs[0], frags[0])["compile_cmd"] == ["__CLANG__", "__SRC__"]
    assert "cascade_size" in to_run_sweep_row(recs[0], frags[0])


def test_drive_targets_skips_targets_that_never_inject():
    targets = [Target(name="err_x", message="m", features=frozenset(),
                      exemplar=None, covered=True)]
    recs = drive_targets(targets, [_frag()], MockVerifier(lambda s, c, l: None),
                         chat=None, inject_fn=lambda *a, **k: None,
                         candidates_per_target=2, max_instances=5)
    assert recs == []
