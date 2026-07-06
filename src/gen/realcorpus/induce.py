"""Verify-and-retry injection: ask for an edit, apply it, verify with the REAL
compile command, and if the primary error is not the target, feed the observed
diagnostic back and retry. Closes the diagnostic loop on GENERATION — the
verifier signal steers the model toward inducing exactly the requested
diagnostic. Returns the first exact match, else None (near-misses are dropped).
"""
from __future__ import annotations

from typing import Callable, Optional

from foundation.types import VerifierResult
from foundation.verifier.base import BaseVerifier
from gen.realcorpus.corpus import Fragment
from gen.realcorpus.inject import _FILE_HEAD_CHARS, apply_edit
from gen.realcorpus.prompt import (build_inject_prompt, build_retry_message,
                                   parse_edit)
from gen.realcorpus.targets import Target

ChatFn = Callable[[list[dict], float], str]


def induce_target(target: Target, fragment: Fragment, chat: ChatFn,
                  verifier: BaseVerifier, *, max_attempts: int = 3,
                  temperature: float = 0.8
                  ) -> Optional[tuple[str, VerifierResult]]:
    messages = build_inject_prompt(target, fragment.region_text,
                                   fragment.tu_src[:_FILE_HEAD_CHARS])
    for _ in range(max(1, max_attempts)):
        try:
            reply = chat(messages, temperature)
        except Exception:
            break
        edit = parse_edit(reply)
        if edit is None:
            break  # NOT_APPLICABLE / unparseable — give up on this fragment
        mutant = apply_edit(fragment.tu_src, edit)
        if mutant is None or mutant == fragment.tu_src:
            messages = messages + [
                {"role": "assistant", "content": reply},
                {"role": "user", "content": "That OLD text was not found verbatim "
                 "and uniquely in the code. Copy an exact, unique snippet."},
            ]
            continue
        res = verifier.verify(mutant, fragment.compile_cmd,
                              logical_path=fragment.rel_path)
        if not res.ok and res.diag is not None:
            if res.diag.diag_name == target.name:
                return mutant, res
            observed = res.diag.diag_name or res.diag.diag_msg
            messages = messages + [
                {"role": "assistant", "content": reply},
                build_retry_message(target, observed, compiled_ok=False),
            ]
        else:
            messages = messages + [
                {"role": "assistant", "content": reply},
                build_retry_message(target, "", compiled_ok=True),
            ]
    return None
