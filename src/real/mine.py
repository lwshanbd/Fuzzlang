"""Extract a real-error Record from PR / issue / commit text (local, LLM-assisted).

Many build-failure PRs and issues paste the actual compiler output plus the fix.
An LLM (DeepSeek, injected as a `chat` callable) pulls out
`{is_compile_error, error_message, broken_code, fixed_code}` from that text; the
diagnostic matcher names the error from its message (no recompile needed); and we
emit a `Record(Origin.REAL)`. This is the clone-free, compiler-free path to
Column-B real-world data, runnable off the national-lab clusters (so it can use
DeepSeek).
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Callable, Optional

from foundation.diagnostics.matcher import DiagnosticMatcher
from foundation.record import Origin, Provenance, Record, Split
from foundation.types import DiagInfo

ChatFn = Callable[[list[dict]], str]

_SYSTEM = (
    "You read a GitHub commit, pull request, or issue and decide whether it is "
    "about a COMPILE error (a C/C++ program the compiler rejected), not a runtime "
    "or logic bug. If it is, extract the compiler's error message, the broken code, "
    "and the fixed code. Reply with ONLY a JSON object with keys: is_compile_error "
    "(bool), error_message (string, the compiler diagnostic text verbatim), "
    "broken_code (string), fixed_code (string). Use empty strings when unknown."
)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def build_extract_prompt(text: str) -> list[dict]:
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": f"Here is the GitHub text:\n\n{text}"},
    ]


def parse_extract(reply: str) -> Optional[dict]:
    """Parse the LLM's JSON reply, tolerating surrounding prose."""
    try:
        return json.loads(reply)
    except (json.JSONDecodeError, TypeError):
        pass
    m = _JSON_RE.search(reply or "")
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _record_id(project: str, ref: str, broken: str) -> str:
    h = hashlib.sha256(f"{project}|{ref}|{broken}".encode()).hexdigest()
    return f"real-{h[:12]}"


def extract_from_text(
    text: str,
    chat: ChatFn,
    *,
    matcher: DiagnosticMatcher,
    project: str,
    ref: str,
    url: str,
    split: Split = Split.EVAL,
    language: str = "c++",
) -> Optional[Record]:
    """Extract a real-error Record from `text`, or None if it is not a usable pair.

    Requires a genuine compile error with both broken and fixed code (so it is a
    core paired record). The diagnostic name comes from the matcher; a real error
    whose message the matcher cannot name is still kept (diag_name=None) — it is
    valid Column-B data, just not attributable to a specific diagnostic.
    """
    data = parse_extract(chat(build_extract_prompt(text)))
    if not data or not data.get("is_compile_error"):
        return None

    error_message = (data.get("error_message") or "").strip()
    broken = (data.get("broken_code") or "").strip()
    fixed = (data.get("fixed_code") or "").strip()
    if not error_message or not broken or not fixed:
        return None

    diag = DiagInfo(
        diag_id=None,
        diag_name=matcher.match(error_message),
        diag_msg=error_message,
        file=f"{project}@{ref}",
        line=0,
        col=0,
        start_byte=0,
        end_byte=0,
        span_snippet="",
    )
    return Record(
        record_id=_record_id(project, ref, broken),
        erroneous_src=broken,
        corrected_src=fixed,
        diagnostics=(diag,),
        provenance=Provenance(
            origin=Origin.REAL,
            source=f"{project}@{ref}",
            detail={"url": url, "matched_diag": diag.diag_name},
        ),
        split=split,
        language=language,
    )
