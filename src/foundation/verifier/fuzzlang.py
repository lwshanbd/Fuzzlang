"""Fuzzlang-modified Clang verifier. Reads the "DiagID: N" line the patch emits.

Requires:
  - clang binary built from stock llvm-project + scripts/patches/0001-*.patch,
  - stock diagtool from the same build (no patch needed — stock diagtool's
    `find-diagnostic-id <int>` already falls back to id-to-name lookup).
  - both on PATH or given explicitly.
"""
from __future__ import annotations

import functools
import os
import re
import subprocess
import tempfile
from typing import Optional

from foundation.types import DiagInfo, VerifierResult
from foundation.verifier.base import PLACEHOLDER, BaseVerifier
from foundation.verifier.stock import _ERROR_LINE, _line_byte_range

_DIAG_ID_LINE = re.compile(r"^DiagID:\s*(\d+)\s*$", re.MULTILINE)


class FuzzlangClangVerifier(BaseVerifier):
    def __init__(
        self,
        clang_bin: str,
        diagtool_bin: str,
        timeout_s: float = 10.0,
        *,
        clang_c_bin: Optional[str] = None,
    ):
        self.clang_bin = clang_bin
        self.clang_c_bin = clang_c_bin or clang_bin
        self.diagtool_bin = diagtool_bin
        self.timeout_s = timeout_s

    def _compiler_for(self, compile_cmd: list[str], logical_path: str) -> str:
        if _guess_suffix(compile_cmd, logical_path) == ".c":
            return self.clang_c_bin
        return self.clang_bin

    def verify(
        self,
        source: str,
        compile_cmd: list[str],
        *,
        logical_path: str,
    ) -> VerifierResult:
        suffix = _guess_suffix(compile_cmd, logical_path)
        compiler = self._compiler_for(compile_cmd, logical_path)
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=suffix,
            delete=False,
        ) as tf:
            tf.write(source)
            tmp_path = tf.name
        try:
            cmd = [compiler if a == "__CLANG__" else
                   tmp_path if a == PLACEHOLDER else a
                   for a in compile_cmd]
            try:
                # errors="replace": some frontend configs emit non-UTF-8 bytes
                # in a diagnostic; strict decoding would crash the run.
                result = subprocess.run(
                    cmd, capture_output=True, text=True, errors="replace",
                    timeout=self.timeout_s,
                )
            except subprocess.TimeoutExpired:
                return VerifierResult(ok=False, diag=None, raw_stderr="__TIMEOUT__")

            if result.returncode == 0:
                return VerifierResult(ok=True, diag=None, raw_stderr=result.stderr)

            diag = self._extract_primary(result.stderr, logical_path, source)
            return VerifierResult(ok=False, diag=diag, raw_stderr=result.stderr)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def _extract_primary(
        self, stderr: str, logical_path: str, src_content: str
    ) -> Optional[DiagInfo]:
        err_m = _ERROR_LINE.search(stderr)
        if not err_m:
            return None
        diag_id: Optional[int] = None
        after = stderr[err_m.end():]
        id_m = _DIAG_ID_LINE.search(after)
        if id_m:
            diag_id = int(id_m.group(1))

        line = int(err_m.group("line"))
        col = int(err_m.group("col"))
        msg = err_m.group("msg").strip()
        start_byte, end_byte, snippet = _line_byte_range(src_content, line)
        diag_name = self._lookup_name(diag_id) if diag_id is not None else None

        return DiagInfo(
            diag_id=diag_id, diag_name=diag_name, diag_msg=msg,
            file=logical_path, line=line, col=col,
            start_byte=start_byte, end_byte=end_byte, span_snippet=snippet,
        )

    @functools.lru_cache(maxsize=2048)
    def _lookup_name(self, diag_id: int) -> Optional[str]:
        # Stock `diagtool find-diagnostic-id <int>` reverses to the name. See
        # clang/tools/diagtool/FindDiagnosticID.cpp in LLVM 19; no patch needed.
        try:
            r = subprocess.run(
                [self.diagtool_bin, "find-diagnostic-id", str(diag_id)],
                capture_output=True, text=True, errors="replace", timeout=5.0,
            )
            if r.returncode == 0:
                name = r.stdout.strip().split("\n", 1)[0]
                return name or None
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return None


def _guess_suffix(
    compile_cmd: list[str], logical_path: Optional[str] = None,
) -> str:
    # 1) Explicit C++ source file path in args.
    for a in compile_cmd:
        if a.endswith((".cpp", ".cc", ".cxx", ".c++")):
            return ".cpp"
    # 2) An explicit -x language overrides filename and standard inference.
    for i, a in enumerate(compile_cmd):
        if (a == "-x" and i + 1 < len(compile_cmd)
                and compile_cmd[i + 1] in ("c++", "objective-c++")):
            return ".cpp"
        if (a == "-x" and i + 1 < len(compile_cmd)
                and compile_cmd[i + 1] in ("c", "objective-c")):
            return ".c"
        if a in ("-xc++", "-xobjective-c++"):
            return ".cpp"
        if a in ("-xc", "-xobjective-c"):
            return ".c"
    # 3) -std=c++... or -std=gnu++... implies C++. Stage 2 emits
    #    compile_cmds with __SRC__ placeholder so the source path is absent.
    for a in compile_cmd:
        if a.startswith(("-std=c++", "-std=gnu++")):
            return ".cpp"
    # 4) Some CMake databases rely on the original .cc/.cpp filename and omit
    #    both -x and -std.  The stable logical path retains that information.
    if logical_path and logical_path.lower().endswith(
        (".cpp", ".cc", ".cxx", ".c++")
    ):
        return ".cpp"
    return ".c"
