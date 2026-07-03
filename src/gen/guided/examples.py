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

from typing import Callable, Iterable, Optional

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


def feature_configs(resource_dir: str) -> list[list[str]]:
    """Verification configs for feature/target-gated CODE diagnostics.

    Many uncovered diagnostics are real code errors that only fire under a
    feature flag or target (OpenMP, ObjC-ARC, HLSL, OpenCL, modules, blocks,
    fixed-point, matrix, SVE/SME/NEON/RISC-V). The LLM tends to synthesize the
    right feature code from the diagnostic name; verifying under these lets the
    pair be kept. Driver-mode where possible; `-cc1` (with the resource dir) for
    target-feature and HLSL.
    """
    def drv(*flags: str) -> list[str]:
        return ["__CLANG__", "-fsyntax-only", *flags, PLACEHOLDER]

    def cc1(*flags: str) -> list[str]:
        return ["__CLANG__", "-cc1", "-resource-dir", resource_dir, *flags,
                "-fsyntax-only", PLACEHOLDER]

    return [
        drv("-fopenmp", "-x", "c++", "-std=c++17"),
        drv("-fopenmp", "-x", "c"),
        drv("-fopenacc", "-x", "c++"),
        drv("-fopenacc", "-x", "c"),
        drv("-fobjc-arc", "-x", "objective-c"),
        drv("-fobjc-arc", "-x", "objective-c++"),
        drv("-x", "objective-c"),              # ObjC without ARC
        drv("-fblocks", "-x", "c"),
        drv("-fmodules", "-fcxx-modules", "-x", "c++", "-std=c++20"),
        drv("-ffixed-point", "-x", "c"),
        drv("-fenable-matrix", "-x", "c++", "-std=c++17"),
        drv("-fenable-matrix", "-x", "c"),
        drv("-fms-extensions", "-fms-compatibility", "-fdeclspec",
            "-fdelayed-template-parsing", "-x", "c++"),
        drv("-fsycl-is-device", "-x", "c++", "-std=c++17"),
        drv("-x", "c++", "-std=c++2c"),        # newest standard (new consteval/etc.)
        drv("-x", "cl"),                       # OpenCL
        drv("-x", "cuda", "--cuda-host-only"),
        cc1("-triple", "dxil-pc-shadermodel6.3-library", "-x", "hlsl"),
        cc1("-triple", "dxil-pc-shadermodel6.6-compute", "-x", "hlsl"),
        cc1("-triple", "aarch64", "-target-feature", "+sve", "-target-feature",
            "+sme", "-target-feature", "+neon", "-x", "c"),
        cc1("-triple", "riscv64", "-target-feature", "+v", "-x", "c"),
        cc1("-triple", "x86_64", "-target-feature", "+avx512f", "-x", "c"),
    ]


def _diags_for_source(
    snippet: str, source_id: str, verifier: BaseVerifier, cmds: list[list[str]]
) -> list[tuple[str, list[str]]]:
    """(diagnostic, triggering config) pairs `snippet` yields across `cmds`.

    Deduped by diagnostic in config order, so each diagnostic is paired with the
    first config that triggered it.
    """
    found: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    for cmd in cmds:
        result = verifier.verify(snippet, cmd, logical_path=source_id)
        if result.ok or result.diag is None or not result.diag.diag_name:
            continue
        name = result.diag.diag_name
        if name not in seen:
            seen.add(name)
            found.append((name, cmd))
    return found


def mine_examples(
    sources: Iterable[tuple[str, str]],
    verifier: BaseVerifier,
    *,
    language: str = "c++",
    compile_cmd: Optional[list[str]] = None,
    compile_cmds: Optional[list[list[str]]] = None,
    per_source_cmds: Optional[Callable[[str, str], list[list[str]]]] = None,
    max_per_diag: Optional[int] = None,
    workers: int = 1,
) -> dict[str, list[str]]:
    """Group snippets by the error diagnostic(s) they trigger (examples only).

    Thin wrapper over :func:`mine` that returns just the ``{diag: [snippet]}``
    index. See :func:`mine` for the full argument docs.

    Args:
        sources: iterable of (snippet, source_id).
        verifier: compile backend (FuzzlangClangVerifier in production).
        language / compile_cmd: single-config compilation (back-compat default).
        compile_cmds: list of configs to sweep and union (e.g. sweep_configs());
            overrides the single-config path.
        per_source_cmds: optional ``(snippet, source_id) -> [config, ...]`` giving
            extra per-file configs (e.g. that file's own ``%clang_cc1`` RUN-line
            flags), unioned with `compile_cmds` for that source only.
        max_per_diag: cap on examples kept per diagnostic (None = unbounded).
        workers: thread pool size for mining (subprocess-bound, so threads help).

    Returns:
        ``{diag_name: [snippet, ...]}``. Snippets that compile clean or trigger an
        unnamed diagnostic under every config are skipped.
    """
    return mine(
        sources, verifier, language=language, compile_cmd=compile_cmd,
        compile_cmds=compile_cmds, per_source_cmds=per_source_cmds,
        max_per_diag=max_per_diag, workers=workers,
    )[0]


def mine(
    sources: Iterable[tuple[str, str]],
    verifier: BaseVerifier,
    *,
    language: str = "c++",
    compile_cmd: Optional[list[str]] = None,
    compile_cmds: Optional[list[list[str]]] = None,
    per_source_cmds: Optional[Callable[[str, str], list[list[str]]]] = None,
    max_per_diag: Optional[int] = None,
    max_configs_per_diag: Optional[int] = None,
    workers: int = 1,
) -> tuple[dict[str, list[str]], dict[str, list[list[str]]]]:
    """Mine, returning both the example index and the triggering configs.

    Same arguments as :func:`mine_examples`, plus `max_configs_per_diag` (cap on
    tracked triggering configs per diagnostic). Returns
    ``(examples, configs)`` where ``configs[diag]`` are the compile configs that
    triggered `diag` (order of first appearance) — used to verify generated pairs
    for RUN-line diagnostics under the flags that can actually trigger them.
    """
    cmds = compile_cmds if compile_cmds is not None else [
        compile_cmd if compile_cmd is not None else default_compile_cmd(language)
    ]
    sources = list(sources)

    def cmds_for(snippet: str, sid: str) -> list[list[str]]:
        if per_source_cmds is None:
            return cmds
        return cmds + per_source_cmds(snippet, sid)

    if workers and workers > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as ex:
            per_source = list(ex.map(
                lambda so: _diags_for_source(so[0], so[1], verifier, cmds_for(*so)),
                sources))
    else:
        per_source = [_diags_for_source(s, sid, verifier, cmds_for(s, sid))
                      for s, sid in sources]

    examples: dict[str, list[str]] = {}
    configs: dict[str, list[list[str]]] = {}
    for (snippet, _sid), diags in zip(sources, per_source):
        for name, cmd in diags:
            bucket = examples.setdefault(name, [])
            if max_per_diag is None or len(bucket) < max_per_diag:
                bucket.append(snippet)
            cfgs = configs.setdefault(name, [])
            if cmd not in cfgs and (max_configs_per_diag is None
                                    or len(cfgs) < max_configs_per_diag):
                cfgs.append(cmd)
    return examples, configs
