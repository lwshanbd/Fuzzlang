"""Tests for compile_commands.json handling shared by real/ and gen/realcorpus."""
from __future__ import annotations

import json
from pathlib import Path

from foundation.compile_db import build_clang_argv, load_compile_db, split_command


def test_load_compile_db_indexes_by_realpath(tmp_path: Path):
    ccdb = tmp_path / "compile_commands.json"
    ccdb.write_text(json.dumps([
        {"directory": "/b", "file": "/src/a.cpp", "command": "g++ -c /src/a.cpp -o a.o"},
    ]))
    db = load_compile_db(ccdb)
    assert "/src/a.cpp" in db


def test_split_command_handles_command_and_arguments():
    assert split_command({"command": "g++ -c a.cpp"}) == ["g++", "-c", "a.cpp"]
    assert split_command({"arguments": ["g++", "-c", "a.cpp"]}) == ["g++", "-c", "a.cpp"]


def test_build_clang_argv_portable_placeholders():
    entry = {"directory": "/b", "file": "/src/a.cpp",
             "command": "g++ -std=c++17 -I/inc -c /src/a.cpp -o /b/a.o"}
    argv = build_clang_argv(entry, "__CLANG__", "__SRC__")
    assert argv[0] == "__CLANG__"
    assert "-o" not in argv and "/b/a.o" not in argv
    assert "/src/a.cpp" not in argv
    assert argv[-1] == "__SRC__"
    assert "-fsyntax-only" in argv and "-fno-color-diagnostics" in argv
    assert "-std=c++17" in argv and "-I/inc" in argv


def test_build_clang_argv_resolves_compile_directory_relative_paths():
    entry = {
        "directory": "/project/build",
        "file": "../src/a.c",
        "arguments": [
            "clang", "-I.", "-I../include", "-isystem", "third_party",
            "-include", "config.h", "-MMD", "-MF", "a.d", "-MT", "a.o",
            "-c", "../src/a.c", "-o", "a.o",
        ],
    }

    argv = build_clang_argv(entry, "__CLANG__", "__SRC__")

    assert "-I/project/build" in argv
    assert "-I/project/include" in argv
    assert argv[argv.index("-isystem") + 1] == "/project/build/third_party"
    assert argv[argv.index("-include") + 1] == "/project/build/config.h"
    assert "-MMD" not in argv and "-MF" not in argv and "a.d" not in argv
    assert "-MT" not in argv and "a.o" not in argv
    assert "../src/a.c" not in argv
    assert argv[argv.index("-iquote") + 1] == "/project/src"
