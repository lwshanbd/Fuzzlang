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

from experiments.types import DiagInfo, VerifierResult
from experiments.verifier.base import PLACEHOLDER, BaseVerifier
from experiments.verifier.stock import _ERROR_LINE, _line_byte_range

_DIAG_ID_LINE = re.compile(r"^DiagID:\s*(\d+)\s*$", re.MULTILINE)


class FuzzlangClangVerifier(BaseVerifier):
    def __init__(self, clang_bin: str, diagtool_bin: str, timeout_s: float = 10.0):
        self.clang_bin = clang_bin
        self.diagtool_bin = diagtool_bin
        self.timeout_s = timeout_s

    def verify(
        self,
        source: str,
        compile_cmd: list[str],
        *,
        logical_path: str,
    ) -> VerifierResult:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=_guess_suffix(compile_cmd), delete=False
        ) as tf:
            tf.write(source)
            tmp_path = tf.name
        try:
            cmd = [self.clang_bin if a == "__CLANG__" else
                   tmp_path if a == PLACEHOLDER else a
                   for a in compile_cmd]
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=self.timeout_s
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
                capture_output=True, text=True, timeout=5.0,
            )
            if r.returncode == 0:
                name = r.stdout.strip().split("\n", 1)[0]
                return name or None
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return None


def _guess_suffix(compile_cmd: list[str]) -> str:
    for a in compile_cmd:
        if a.endswith((".cpp", ".cc", ".cxx", ".c++")):
            return ".cpp"
    return ".c"
