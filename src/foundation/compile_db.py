"""Parse compile_commands.json and turn a recorded compile command into a
portable, verifier-runnable form. Shared by `real/` (real-error reproduction)
and `gen/realcorpus/` (real-code error injection).

`build_clang_argv` replaces the compiler with a placeholder, drops `-o`, strips
the recorded source path, forces `-fsyntax-only -fno-color-diagnostics`, and
appends a source placeholder — yielding the `[__CLANG__ ... __SRC__]` shape the
FuzzlangClangVerifier substitutes.
"""
from __future__ import annotations

import json
import os
import shlex
from pathlib import Path


def load_compile_db(ccdb_path: Path) -> dict[str, dict]:
    """Index compile_commands.json by absolute (realpath) source file."""
    with Path(ccdb_path).open() as f:
        rows = json.load(f)
    index: dict[str, dict] = {}
    for r in rows:
        fpath = os.path.realpath(
            r["file"] if os.path.isabs(r["file"])
            else os.path.join(r.get("directory", ""), r["file"])
        )
        index[fpath] = r
    return index


def split_command(entry: dict) -> list[str]:
    """Return the argv list from a `command` (string) or `arguments` (list) entry."""
    if "arguments" in entry:
        return list(entry["arguments"])
    return shlex.split(entry["command"])


def build_clang_argv(entry: dict, clang_bin: str, src: str) -> list[str]:
    """Portable-ize a recorded compile command for buggy/injected source.

    - Replace the compiler (argv[0]) with `clang_bin`.
    - Drop `-o <out>`.
    - Drop the recorded source path.
    - Force `-fsyntax-only` and `-fno-color-diagnostics`.
    - Append `src` as the (only) source argument.
    """
    argv = split_command(entry)
    argv[0] = clang_bin
    entry_file = os.path.realpath(
        entry["file"] if os.path.isabs(entry["file"])
        else os.path.join(entry.get("directory", ""), entry["file"])
    )
    directory = entry.get("directory") or os.path.dirname(entry_file)

    def portable_path(value: str) -> str:
        if not value or os.path.isabs(value):
            return value
        return os.path.normpath(os.path.join(directory, value))

    out: list[str] = [clang_bin]
    path_options = frozenset({"-I", "-isystem", "-iquote", "-include", "-imacros"})
    dependency_output_options = frozenset({"-MF", "-MT", "-MQ"})
    index = 1
    while index < len(argv):
        tok = argv[index]
        if tok == "-o" or tok in dependency_output_options:
            index += 2
            continue
        if tok in {"-MD", "-MMD"}:
            index += 1
            continue
        if tok in path_options:
            if index + 1 >= len(argv):
                out.append(tok)
                index += 1
                continue
            out.extend((tok, portable_path(argv[index + 1])))
            index += 2
            continue
        if tok.startswith("-I") and tok != "-I":
            out.append("-I" + portable_path(tok[2:]))
            index += 1
            continue
        source_candidate = (
            tok if os.path.isabs(tok) else os.path.join(directory, tok)
        )
        if os.path.realpath(source_candidate) == entry_file:
            index += 1
            continue
        out.append(tok)
        index += 1
    # The verifier compiles a temporary replacement file.  Preserve the
    # compiler's implicit quote-include search beside the original source.
    # This is essential for projects such as FFmpeg that use "header.h" files
    # colocated with each translation unit.
    out.extend(("-iquote", os.path.dirname(entry_file)))
    if "-fsyntax-only" not in out:
        out.append("-fsyntax-only")
    if "-fno-color-diagnostics" not in out:
        out.append("-fno-color-diagnostics")
    out.append(src)
    return out
