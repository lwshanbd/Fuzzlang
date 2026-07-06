"""Build the injection chat messages and parse the model's reply.

The model is asked to introduce EXACTLY ONE minimal edit into the given region
so clang emits the target diagnostic, returning an anchored old/new block:

    <<<OLD
    <exact snippet currently in the region>
    ===
    <replacement>
    >>>

or the literal `NOT_APPLICABLE` if the target cannot be naturally induced here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from gen.realcorpus.targets import Target

_SYSTEM = (
    "You corrupt correct C/C++ code to create a SPECIFIC compiler error, for a "
    "compiler-diagnostics dataset. You are given a target Clang diagnostic, an "
    "example of how it is triggered, and a region of real code. Introduce the "
    "SMALLEST possible edit to the region so that the FIRST error Clang emits is "
    "exactly the target diagnostic. Prefer a SEMANTIC change (wrong type, wrong "
    "name, wrong overload, bad member/conversion) over trivial syntax breakage, "
    "unless the target is itself a syntactic diagnostic. Keep the edit local and "
    "realistic. Reply with ONE block:\n"
    "<<<OLD\n<exact text to replace, copied verbatim from the region>\n===\n"
    "<replacement text>\n>>>\n"
    "If the target diagnostic cannot be naturally induced in this region, reply "
    "with exactly NOT_APPLICABLE and nothing else."
)

_BLOCK = re.compile(r"<<<OLD\s*\n(.*?)\n===\s*\n(.*?)\n?>>>", re.DOTALL)


@dataclass(frozen=True)
class Edit:
    old: str
    new: str


def build_inject_prompt(target: Target, region_text: str,
                        file_head: str) -> list[dict]:
    exemplar = target.exemplar or "(no example available)"
    user = (
        f"Target diagnostic: {target.name}\n"
        f"Diagnostic message: {target.message}\n\n"
        f"Example that triggers it elsewhere:\n{exemplar}\n\n"
        f"File context (top of file):\n{file_head}\n\n"
        f"Region to edit:\n{region_text}\n"
    )
    return [{"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user}]


def parse_edit(reply: str) -> Optional[Edit]:
    if "NOT_APPLICABLE" in reply and not _BLOCK.search(reply):
        return None
    m = _BLOCK.search(reply)
    if not m:
        return None
    return Edit(old=m.group(1), new=m.group(2))


def build_retry_message(target: Target, observed: str,
                        compiled_ok: bool) -> dict:
    """A follow-up user turn telling the model how its last edit missed, so it
    can correct toward making the FIRST Clang error equal the target."""
    if compiled_ok:
        body = (
            f"Your edit did NOT cause any compiler error. Make a change so the "
            f"FIRST error Clang emits is {target.name} ({target.message})."
        )
    else:
        body = (
            f"Your edit produced '{observed}' as the first error, but I need the "
            f"FIRST error to be {target.name} ({target.message}). Revise the edit "
            f"so Clang's first error is {target.name}."
        )
    return {"role": "user",
            "content": body + "\nReply with ONE <<<OLD ... === ... >>> block, "
                              "or NOT_APPLICABLE."}
