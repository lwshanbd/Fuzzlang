from __future__ import annotations

from real.reproduce_stage2_llvm import _build_clang_argv


def _entry(*arguments: str) -> dict:
    return {
        "directory": "/build",
        "file": "/src/llvm/lib/Analysis/Foo.cpp",
        "arguments": ["/usr/bin/c++", *arguments, "-c", "/src/llvm/lib/Analysis/Foo.cpp"],
    }


def test_werror_is_dropped_so_a_stale_warning_flag_cannot_reject_the_fix():
    # LLVM is built with -Werror and carries GCC-only suppressions such as
    # -Wno-class-memaccess.  Clang answers those with
    # -Wunknown-warning-option, which -Werror promotes to an error -- so the
    # *fixed* revision of a file fails to compile and the pair is thrown away.
    # This cost 240 of 269 NatErr candidates before it was fixed.  We are
    # asking whether the source has a compilation error, not whether it
    # satisfies the project's warning policy.
    argv = _build_clang_argv(
        _entry("-Werror", "-Werror=return-type", "-Wno-class-memaccess", "-O2"),
        "__CLANG__", "__SRC__",
    )

    assert not [token for token in argv if token.startswith("-Werror")]
    # Everything else about the command survives, including the suppression
    # itself: dropping it would change which diagnostics can fire.
    assert "-Wno-class-memaccess" in argv
    assert "-O2" in argv
    assert "-fsyntax-only" in argv
    assert argv[-1] == "__SRC__"


def test_include_paths_and_placeholders_are_preserved():
    argv = _build_clang_argv(
        _entry("-I/src/llvm/include", "-Iinclude", "-std=c++17"),
        "__CLANG__", "__SRC__",
    )

    assert argv[0] == "__CLANG__"
    assert "-I/src/llvm/include" in argv
    assert "-I/build/include" in argv  # resolved against the compile directory
    assert "-std=c++17" in argv
