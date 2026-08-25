from __future__ import annotations

import pytest

from foundation.record import Origin, Provenance, Record, Split
from foundation.types import DiagInfo
from repair.agent.chat_backend import ChatResponse, MockChatBackend
from repair.run_adapter_eval import generate_via_chat_backend
from repair.sft_data import make_localized_repair_example


def _example():
    record = Record(
        record_id="r0",
        erroneous_src="int main() { return missing; }\n",
        corrected_src="int main() { return 0; }\n",
        diagnostics=(DiagInfo(
            diag_id=1, diag_name="err_undeclared_var_use",
            diag_msg="use of undeclared identifier 'missing'",
            file="a.cpp", line=1, col=21, start_byte=0, end_byte=10,
            span_snippet="missing",
        ),),
        provenance=Provenance(origin=Origin.MUTATE, source="p:a.cpp", detail={}),
        split=Split.EVAL,
        language="c++",
    )
    return make_localized_repair_example(record.to_dict())


def test_the_served_model_sees_the_prompt_the_local_model_would_have():
    # The whole point of a second backend is that only the *execution* changes.
    # If the messages differ, the 31B is answering a different exam and the
    # comparison against the fine-tuned arms is meaningless.
    backend = MockChatBackend([[ChatResponse(text='{"corrected_window": "x"}',
                                             output_tokens=7)]])

    generate_via_chat_backend(
        backend, _example(), max_new_tokens=512, target_format="window-rewrite",
    )

    call = backend.call_log[0]
    # One user turn, and the assistant turn withheld -- the model is being asked
    # to produce it, not shown it.
    assert [m["role"] for m in call["messages"]] == ["user"]
    assert "err_undeclared_var_use" in call["messages"][0]["content"]
    assert call["max_tokens"] == 512


def test_decoding_is_greedy_so_the_run_is_reproducible():
    backend = MockChatBackend([[ChatResponse(text="{}", output_tokens=1)]])

    generate_via_chat_backend(
        backend, _example(), max_new_tokens=64, target_format="window-rewrite",
    )

    assert backend.call_log[0]["temperature"] == 0.0
    assert backend.call_log[0]["n"] == 1


def test_the_completion_text_is_returned_stripped():
    backend = MockChatBackend([[ChatResponse(text='  {"corrected_window": "y"}\n',
                                             output_tokens=9)]])

    text = generate_via_chat_backend(
        backend, _example(), max_new_tokens=64, target_format="window-rewrite",
    )

    assert text == '{"corrected_window": "y"}'


def test_an_empty_completion_list_is_an_error_not_an_empty_answer():
    # An empty answer would be scored as an unparseable prediction and quietly
    # counted as a failed repair; a server that returned nothing is a bug.
    with pytest.raises(ValueError):
        generate_via_chat_backend(
            MockChatBackend([[]]), _example(),
            max_new_tokens=64, target_format="window-rewrite",
        )


def test_concurrency_does_not_change_the_order_or_content_of_results():
    # vLLM answers many requests at once; sending one at a time leaves the
    # server idle between calls. Overlapping them is only safe if the archived
    # per-instance results are identical, in the same order, at any width.
    from repair.run_adapter_eval import map_with_concurrency

    def work(n):
        return n * 2

    serial = map_with_concurrency(work, list(range(20)), concurrency=1)
    parallel = map_with_concurrency(work, list(range(20)), concurrency=8)

    assert serial == parallel == [n * 2 for n in range(20)]


def test_a_failure_inside_a_worker_is_not_swallowed():
    from repair.run_adapter_eval import map_with_concurrency

    def work(n):
        if n == 3:
            raise RuntimeError("boom")
        return n

    with pytest.raises(RuntimeError):
        map_with_concurrency(work, list(range(6)), concurrency=4)


def test_concurrency_must_be_at_least_one():
    from repair.run_adapter_eval import map_with_concurrency

    with pytest.raises(ValueError):
        map_with_concurrency(lambda n: n, [1], concurrency=0)
