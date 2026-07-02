"""Tests for guided pair generation (LLM -> verify -> Record)."""
from foundation.record import Origin
from foundation.types import DiagInfo, VerifierResult
from foundation.verifier.mock import MockVerifier, ok_result
from gen.guided.generate import generate_pair, generate_pairs, parse_pair

GOOD_REPLY = """Sure.
CORRECT:
```cpp
int main() { int x = 0; return x; }
```
BROKEN:
```cpp
int main() { int x = 0 return x; }
```
"""


def _diag(name="err_expected_semi_after_expr"):
    return DiagInfo(diag_id=42, diag_name=name, diag_msg="expected ';'",
                    file="g.cpp", line=1, col=10, start_byte=5, end_byte=6,
                    span_snippet="0")


def _chat(reply):
    return lambda messages: reply


def _correct_ok_broken_err(diag):
    """policy: the broken block (contains '0 return') errors; everything else compiles."""
    def policy(source, cmd, logical_path):
        if "0 return" in source:
            return VerifierResult(ok=False, diag=diag, raw_stderr="error: expected ';'")
        return ok_result()
    return policy


def test_parse_pair_extracts_two_blocks():
    correct, broken = parse_pair(GOOD_REPLY)
    assert "return x;" in correct
    assert "0 return" in broken


def test_parse_pair_none_when_fewer_than_two_blocks():
    assert parse_pair("only ```cpp\nint x;\n``` here") is None


def test_generate_pair_emits_guided_record():
    diag = _diag()
    rec = generate_pair("err_expected_semi_after_expr", "expected ';'",
                        "int a = 0 ;", _chat(GOOD_REPLY),
                        MockVerifier(_correct_ok_broken_err(diag)), source="ex:t1")
    assert rec is not None
    assert rec.provenance.origin is Origin.GUIDED
    assert rec.is_core
    assert rec.corrected_src.strip().startswith("int main()")
    assert "0 return" in rec.erroneous_src
    assert rec.primary_diagnostic.diag_name == "err_expected_semi_after_expr"
    assert rec.provenance.detail["target_diag"] == "err_expected_semi_after_expr"
    assert rec.provenance.detail["matched_target"] is True


def test_rejected_when_correct_does_not_compile():
    v = MockVerifier(lambda s, c, l: VerifierResult(ok=False, diag=_diag(), raw_stderr="e"))
    assert generate_pair("err_x", "m", "ex", _chat(GOOD_REPLY), v, source="s") is None


def test_rejected_when_broken_compiles():
    v = MockVerifier(lambda s, c, l: ok_result())
    assert generate_pair("err_x", "m", "ex", _chat(GOOD_REPLY), v, source="s") is None


def test_none_on_unparseable_reply():
    v = MockVerifier(lambda s, c, l: ok_result())
    assert generate_pair("err_x", "m", "ex", _chat("no code here"), v, source="s") is None


def test_target_required_rejects_other_diagnostic():
    diag = _diag("err_something_else")
    v = MockVerifier(_correct_ok_broken_err(diag))
    assert generate_pair("err_target", "m", "ex", _chat(GOOD_REPLY), v,
                         source="s", target_required=True) is None


def test_default_keeps_actual_diagnostic_when_not_target():
    diag = _diag("err_something_else")
    v = MockVerifier(_correct_ok_broken_err(diag))
    rec = generate_pair("err_target", "m", "ex", _chat(GOOD_REPLY), v, source="s")
    assert rec is not None
    assert rec.primary_diagnostic.diag_name == "err_something_else"
    assert rec.provenance.detail["matched_target"] is False


# ---- generate_pairs: multiple samples per diagnostic ------------------------

def _reply(correct, broken):
    return f"CORRECT:\n```cpp\n{correct}\n```\nBROKEN:\n```cpp\n{broken}\n```"


def _brk_policy(diag):
    """Sources containing the /*BRK*/ marker error with `diag`; others compile."""
    def policy(source, cmd, logical_path):
        if "/*BRK*/" in source:
            return VerifierResult(ok=False, diag=diag, raw_stderr="error")
        return ok_result()
    return policy


def _seq_chat(replies):
    it = iter(replies)
    return lambda messages: next(it)


def test_generate_pairs_produces_multiple_distinct_records():
    diag = _diag()
    replies = [_reply("int main(){return 0;}", f"int a=0 /*BRK*/{k};") for k in range(3)]
    recs = generate_pairs("err_expected_semi_after_expr", "m", ["ex"],
                          _seq_chat(replies), MockVerifier(_brk_policy(diag)),
                          source="ex:t", samples=3)
    assert len(recs) == 3
    assert len({r.erroneous_src for r in recs}) == 3
    assert all(r.provenance.origin is Origin.GUIDED for r in recs)


def test_generate_pairs_dedups_identical_broken():
    diag = _diag()
    same = _reply("int main(){return 0;}", "int a=0 /*BRK*/;")
    recs = generate_pairs("err_x", "m", ["ex"], _chat(same),
                          MockVerifier(_brk_policy(diag)), source="s", samples=3)
    assert len(recs) == 1


def test_generate_pairs_samples_one_matches_single():
    diag = _diag()
    recs = generate_pairs("err_x", "m", ["ex"],
                          _chat(_reply("int main(){return 0;}", "int a=0 /*BRK*/;")),
                          MockVerifier(_brk_policy(diag)), source="s", samples=1)
    assert len(recs) == 1


def test_generate_pairs_cycles_through_examples():
    diag = _diag()
    seen = []

    def chat(messages):
        content = messages[-1]["content"]
        mark = "EXA" if "EXA" in content else "EXB"
        seen.append(mark)
        return _reply("int main(){return 0;}", f"int x=0 /*BRK*/{mark};")

    recs = generate_pairs("err_x", "m", ["EXA", "EXB"], chat,
                          MockVerifier(_brk_policy(diag)), source="s", samples=2)
    assert set(seen) == {"EXA", "EXB"}   # both mined examples were used
    assert len(recs) == 2
