"""Apply an anchored edit to a TU and drive one target-injection attempt.

`chat` is any callable `(messages, temperature) -> reply_text` (the same shape
used by gen/run_scope). Returns the erroneous TU source, or None if the model
declines / the edit can't be uniquely applied within `retries`.
"""
from __future__ import annotations

from typing import Callable, Optional

from gen.realcorpus.corpus import Fragment
from gen.realcorpus.prompt import Edit, build_inject_prompt, parse_edit
from gen.realcorpus.targets import Target

ChatFn = Callable[[list[dict], float], str]

_FILE_HEAD_CHARS = 1200


def apply_edit(tu_src: str, edit: Edit, *,
               span: Optional[tuple[int, int]] = None) -> Optional[str]:
    """Replace a UNIQUE occurrence of edit.old with edit.new. None if the anchor
    is absent or appears more than once (ambiguous)."""
    start, end = span if span is not None else (0, len(tu_src))
    region = tu_src[start:end]
    if not edit.old or region.count(edit.old) != 1:
        return None
    changed = region.replace(edit.old, edit.new, 1)
    return tu_src[:start] + changed + tu_src[end:]


def inject_target(target: Target, fragment: Fragment, chat: ChatFn, *,
                  retries: int = 2, temperature: float = 0.8) -> Optional[str]:
    file_head = fragment.tu_src[:_FILE_HEAD_CHARS]
    messages = build_inject_prompt(target, fragment.region_text, file_head)
    for _ in range(max(1, retries)):
        try:
            reply = chat(messages, temperature)
        except Exception:
            continue
        edit = parse_edit(reply)
        if edit is None:
            continue
        mutant = apply_edit(fragment.tu_src, edit, span=fragment.span)
        if mutant is not None and mutant != fragment.tu_src:
            return mutant
    return None
