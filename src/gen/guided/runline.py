"""Parse ``%clang_cc1`` RUN-line flags from Clang test files into cc1 configs.

Clang's tests encode the exact frontend flags each diagnostic needs on their
``// RUN: %clang_cc1 ...`` lines. Replaying those flags as
``clang -cc1 <flags> -fsyntax-only`` (with the resource dir added for builtin
headers) triggers diagnostics the language-only sweep never reaches:
target-feature (SVE/SME/neon), OpenMP, MS extensions, and so on.

We keep the frontend flags and drop lit machinery: the ``%clang_cc1`` driver
token, source/temp substitutions, ``-verify``, output/action flags (``-o``,
``-emit-*``, ``-S``, ``-ast-dump``, ``-analyze`` …) and anything piped to a
checker. ``-fsyntax-only`` is forced so we only pay for the front end.
"""
from __future__ import annotations

import re

from foundation.verifier.base import PLACEHOLDER

_RUN_RE = re.compile(r"//\s*RUN:\s*(.*?)\s*$")

# Flags that take a following argument we must drop together (output/plumbing).
_DROP_WITH_ARG = {"-o", "-main-file-name", "-dependency-file", "-MT", "-MF"}
# Action/output flags (no useful diagnostic) — drop the flag alone.
_DROP_FLAGS = {
    "-verify", "-fsyntax-only", "-S", "-emit-llvm", "-emit-llvm-bc",
    "-emit-llvm-only", "-emit-obj", "-emit-pch", "-emit-module",
    "-emit-interface-stubs", "-emit-header-unit", "-E", "-analyze",
    "-rewrite-objc", "-rewrite-legacy-objc",
}
_DROP_PREFIXES = ("-ast-dump", "-ast-print", "-dump", "-print-",
                  "-verify=", "-fdump")


def _runline_commands(text: str) -> list[str]:
    """Return the raw command string of each RUN line, joining ``\\`` continuations."""
    cmds: list[str] = []
    pending = ""
    for line in text.splitlines():
        m = _RUN_RE.search(line)
        if not m:
            continue
        part = m.group(1)
        if part.endswith("\\"):
            pending += part[:-1] + " "
            continue
        cmds.append(pending + part)
        pending = ""
    if pending:
        cmds.append(pending)
    return cmds


def _filter_flags(cmd: str) -> list[str]:
    cmd = cmd.split("|", 1)[0]          # drop pipes to FileCheck/not/etc.
    cmd = re.sub(r"2?>\s*\S+", "", cmd)  # drop redirections
    toks = cmd.split()
    out: list[str] = []
    # Skip everything up to and including the driver token: the single
    # `%clang_cc1` substitution, or a `%clang ... -cc1` pair.
    i = 0
    for j, t in enumerate(toks):
        if "clang_cc1" in t or t == "-cc1":
            i = j + 1
            break
    while i < len(toks):
        t = toks[i]
        if t in _DROP_WITH_ARG:
            i += 2
            continue
        if (t in _DROP_FLAGS or t.startswith(_DROP_PREFIXES)
                or "%" in t or t == "-"):
            i += 1
            continue
        out.append(t)
        i += 1
    return out


def parse_cc1_configs(text: str, *, resource_dir: str) -> list[list[str]]:
    """Extract cc1 compile configs from a test file's ``%clang_cc1`` RUN lines.

    Each config is ``[__CLANG__, -cc1, -resource-dir, <dir>, <flags...>,
    -fsyntax-only, __SRC__]`` with placeholder tokens the verifier substitutes.
    RUN lines that do not invoke ``%clang_cc1`` are ignored. Duplicate configs
    are removed while preserving order.
    """
    configs: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for cmd in _runline_commands(text):
        if "%clang_cc1" not in cmd and "-cc1" not in cmd:
            continue
        flags = _filter_flags(cmd)
        config = ["__CLANG__", "-cc1", "-resource-dir", resource_dir,
                  *flags, "-fsyntax-only", PLACEHOLDER]
        key = tuple(config)
        if key not in seen:
            seen.add(key)
            configs.append(config)
    return configs


def parse_driver_configs(text: str) -> list[list[str]]:
    """Extract safe frontend-only configs from ``%clang``/``%clangxx`` RUN lines."""
    configs: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for command in _runline_commands(text):
        if ("%clang_cc1" in command or "%clang_analyze_cc1" in command
                or "%clang_cl" in command or "-cc1" in command):
            continue
        tokens = command.split("|", 1)[0].split()
        start = next((i for i, token in enumerate(tokens)
                      if token.startswith("%clang")), None)
        if start is None or "-###" in tokens[start + 1:]:
            continue
        flags: list[str] = []
        i = start + 1
        while i < len(tokens):
            token = tokens[i]
            if token in _DROP_WITH_ARG:
                i += 2
            elif token in _DROP_FLAGS or token in {"-c", "-###"}:
                i += 1
            elif token.startswith(_DROP_PREFIXES) or token.startswith("%"):
                i += 1
            elif token in {"not", "2>&1", "2>", "1>"}:
                i += 1
            elif token in {"-I", "-isystem", "-include", "-imacros"} and (
                i + 1 >= len(tokens) or tokens[i + 1].startswith("%")
            ):
                i += 2
            else:
                flags.append(token)
                i += 1
        config = ["__CLANG__", *flags, "-fsyntax-only", PLACEHOLDER]
        key = tuple(config)
        if key not in seen:
            seen.add(key)
            configs.append(config)
    return configs


def parse_analyzer_configs(text: str, *, resource_dir: str) -> list[list[str]]:
    """Extract ``%clang_analyze_cc1`` commands without losing ``-analyze``."""
    configs: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for command in _runline_commands(text):
        if "%clang_analyze_cc1" not in command:
            continue
        flags = _filter_flags(command)
        config = ["__CLANG__", "-cc1", "-resource-dir", resource_dir,
                  *flags, "-analyze", PLACEHOLDER]
        key = tuple(config)
        if key not in seen:
            seen.add(key)
            configs.append(config)
    return configs


def parse_cl_configs(text: str) -> list[list[str]]:
    """Extract syntax-only ``%clang_cl`` driver commands."""
    configs: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for command in _runline_commands(text):
        if "%clang_cl" not in command:
            continue
        tokens = command.split("|", 1)[0].split()
        start = next((i for i, token in enumerate(tokens)
                      if token.startswith("%clang_cl")), None)
        if start is None or "-###" in tokens[start + 1:]:
            continue
        flags: list[str] = []
        i = start + 1
        while i < len(tokens):
            token = tokens[i]
            if token in _DROP_WITH_ARG:
                i += 2
            elif token in _DROP_FLAGS or token in {"-c", "/c", "-###"}:
                i += 1
            elif token.startswith(_DROP_PREFIXES) or token.startswith("%"):
                i += 1
            elif token in {"not", "2>&1", "2>", "1>"}:
                i += 1
            else:
                flags.append(token)
                i += 1
        config = ["__CLANG__", "--driver-mode=cl", *flags, "/Zs", PLACEHOLDER]
        key = tuple(config)
        if key not in seen:
            seen.add(key)
            configs.append(config)
    return configs
