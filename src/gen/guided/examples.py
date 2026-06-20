"""Mine example snippets per diagnostic from a corpus (e.g. Clang's tests).

Run each candidate snippet through the verifier and group the ones that trigger
a named error diagnostic by that diagnostic. The resulting index
(``{diag_name: [snippet, ...]}``) feeds guided pair generation: each snippet is
an example of the diagnostic the LLM is asked to reproduce in a fresh program.
"""
from __future__ import annotations

from typing import Iterable, Optional

from foundation.verifier.base import BaseVerifier
from gen.collect import default_compile_cmd


def mine_examples(
    sources: Iterable[tuple[str, str]],
    verifier: BaseVerifier,
    *,
    language: str = "c++",
    compile_cmd: Optional[list[str]] = None,
    max_per_diag: Optional[int] = None,
) -> dict[str, list[str]]:
    """Group snippets by the error diagnostic they trigger.

    Args:
        sources: iterable of (snippet, source_id).
        verifier: compile backend (FuzzlangClangVerifier in production).
        language / compile_cmd: how to compile (defaults to syntax-only).
        max_per_diag: cap on examples kept per diagnostic (None = unbounded).

    Returns:
        ``{diag_name: [snippet, ...]}``. Snippets that compile clean or trigger an
        unnamed diagnostic are skipped.
    """
    cmd = compile_cmd if compile_cmd is not None else default_compile_cmd(language)
    index: dict[str, list[str]] = {}
    for snippet, source_id in sources:
        result = verifier.verify(snippet, cmd, logical_path=source_id)
        if result.ok or result.diag is None or not result.diag.diag_name:
            continue
        bucket = index.setdefault(result.diag.diag_name, [])
        if max_per_diag is None or len(bucket) < max_per_diag:
            bucket.append(snippet)
    return index
