"""Stock-Clang verifier. Returns ok status + raw stderr + positional info.

Stock Clang does NOT emit the internal diagnostic ID or name. This backend
therefore leaves DiagInfo.diag_id and DiagInfo.diag_name as None. It is
sufficient for:
  - the B1 stderr-loop baseline,
  - the DVCR − structure ablation (raw-stderr observation),
  - CPU-only development before the Fuzzlang-modified Clang is built.
It is NOT sufficient for the DVCR full observation or the DVCR − id ablation,
which require the typed diagnostic ID.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from typing import Optional

from experiments.types import DiagInfo, VerifierResult
from experiments.verifier.base import PLACEHOLDER, BaseVerifier

_ERROR_LINE = re.compile(
    r"^(?P<file>[^:\n]+):(?P<line>\d+):(?P<col>\d+):\s*(?:fatal\s+)?error:\s*(?P<msg>.*)$",
    re.MULTILINE,
)


class StockClangVerifier(BaseVerifier):
    def __init__(self, clang_bin: str = "clang", timeout_s: float = 10.0):
        self.clang_bin = clang_bin
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
                return VerifierResult(ok=False, diag=None,
                                      raw_stderr="__TIMEOUT__")

            if result.returncode == 0:
                return VerifierResult(ok=True, diag=None, raw_stderr=result.stderr)

            diag = _extract_primary_error(result.stderr, logical_path, source)
            return VerifierResult(ok=False, diag=diag, raw_stderr=result.stderr)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _guess_suffix(compile_cmd: list[str]) -> str:
    for a in compile_cmd:
        if a.endswith((".cpp", ".cc", ".cxx", ".c++")):
            return ".cpp"
    return ".c"


def _extract_primary_error(
    stderr: str, logical_path: str, src_content: str
) -> Optional[DiagInfo]:
    m = _ERROR_LINE.search(stderr)
    if not m:
        return None
    line = int(m.group("line"))
    col = int(m.group("col"))
    msg = m.group("msg").strip()
    start_byte, end_byte, snippet = _line_byte_range(src_content, line)

    return DiagInfo(
        diag_id=None,                  # stock Clang does not emit it
        diag_name=None,                # stock Clang does not emit it
        diag_msg=msg,
        file=logical_path,             # stable project-relative path, not the tempfile
        line=line,
        col=col,
        start_byte=start_byte,
        end_byte=end_byte,
        span_snippet=snippet,
    )


def _line_byte_range(src: str, line_1based: int) -> tuple[int, int, str]:
    """Return (start_byte, end_byte_exclusive, line_text_without_newline) for 1-based line.

    Byte offsets are true UTF-8 byte offsets, not Python character counts.
    """
    offset_bytes = 0
    for idx, ln in enumerate(src.splitlines(keepends=True), start=1):
        ln_bytes_len = len(ln.encode("utf-8"))
        if idx == line_1based:
            without_nl = ln.rstrip("\r\n")
            end_bytes_len = len(without_nl.encode("utf-8"))
            return offset_bytes, offset_bytes + end_bytes_len, without_nl
        offset_bytes += ln_bytes_len
    return offset_bytes, offset_bytes, ""
