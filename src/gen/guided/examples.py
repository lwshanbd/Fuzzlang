"""Mine example snippets per diagnostic from a corpus (e.g. Clang's tests).

Run each candidate snippet through the verifier and group the ones that trigger
a named error diagnostic by that diagnostic. The resulting index
(``{diag_name: [snippet, ...]}``) feeds guided pair generation: each snippet is
an example of the diagnostic the LLM is asked to reproduce in a fresh program.

Breadth comes from the **multi-config sweep**: Clang's tests target many
languages and standards (C89..C++2b, Objective-C), so a single
``-std=c++17 -fsyntax-only`` invocation mismines most files (a C file even errors
on the driver flag). Trying several configs per snippet and unioning the
diagnostics each triggers covers far more distinct diagnostic *kinds*.
"""
from __future__ import annotations

from typing import Iterable, Optional

from foundation.verifier.base import PLACEHOLDER, BaseVerifier
from gen.collect import default_compile_cmd


def sweep_configs() -> list[list[str]]:
    """Compile configs spanning C/C++/Objective-C and several standards.

    Each is a compile command with the ``__CLANG__`` / ``__SRC__`` placeholder
    tokens the verifier substitutes. Syntax-only: we only need the front-end
    diagnostic, not codegen (so no backend/target is required).
    """
    def cfg(*flags: str) -> list[str]:
        return ["__CLANG__", "-fsyntax-only", *flags, PLACEHOLDER]

    return [
        cfg("-x", "c++", "-std=c++2b"),
        cfg("-x", "c++", "-std=c++17"),
        cfg("-x", "c++", "-std=c++11"),
        cfg("-x", "c++", "-std=c++98"),
        cfg("-x", "c", "-std=c2x"),
        cfg("-x", "c", "-std=c11"),
        cfg("-x", "c", "-std=c89"),
        cfg("-x", "objective-c++"),
        cfg("-x", "objective-c"),
    ]


def _diags_for_source(
    snippet: str, source_id: str, verifier: BaseVerifier, cmds: list[list[str]]
) -> list[str]:
    """Named error diagnostics `snippet` triggers across `cmds` (deduped, in order)."""
    found: list[str] = []
    seen: set[str] = set()
    for cmd in cmds:
        result = verifier.verify(snippet, cmd, logical_path=source_id)
        if result.ok or result.diag is None or not result.diag.diag_name:
            continue
        name = result.diag.diag_name
        if name not in seen:
            seen.add(name)
            found.append(name)
    return found


def mine_examples(
    sources: Iterable[tuple[str, str]],
    verifier: BaseVerifier,
    *,
    language: str = "c++",
    compile_cmd: Optional[list[str]] = None,
    compile_cmds: Optional[list[list[str]]] = None,
    max_per_diag: Optional[int] = None,
    workers: int = 1,
) -> dict[str, list[str]]:
    """Group snippets by the error diagnostic(s) they trigger.

    Args:
        sources: iterable of (snippet, source_id).
        verifier: compile backend (FuzzlangClangVerifier in production).
        language / compile_cmd: single-config compilation (back-compat default).
        compile_cmds: list of configs to sweep and union (e.g. sweep_configs());
            overrides the single-config path.
        max_per_diag: cap on examples kept per diagnostic (None = unbounded).
        workers: thread pool size for mining (subprocess-bound, so threads help).

    Returns:
        ``{diag_name: [snippet, ...]}``. Snippets that compile clean or trigger an
        unnamed diagnostic under every config are skipped.
    """
    cmds = compile_cmds if compile_cmds is not None else [
        compile_cmd if compile_cmd is not None else default_compile_cmd(language)
    ]
    sources = list(sources)

    if workers and workers > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as ex:
            per_source = list(ex.map(
                lambda so: _diags_for_source(so[0], so[1], verifier, cmds), sources))
    else:
        per_source = [_diags_for_source(s, sid, verifier, cmds) for s, sid in sources]

    index: dict[str, list[str]] = {}
    for (snippet, _sid), diags in zip(sources, per_source):
        for name in diags:
            bucket = index.setdefault(name, [])
            if max_per_diag is None or len(bucket) < max_per_diag:
                bucket.append(snippet)
    return index
