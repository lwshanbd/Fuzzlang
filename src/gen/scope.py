"""Classify diagnostics as strict C/C++ (in scope) vs non-C/C++ dialect/target.

The dataset targets standard C and C++ compilation errors. Diagnostics specific
to another dialect (Objective-C, OpenMP, OpenACC, OpenCL, CUDA/HIP, SYCL, HLSL,
Microsoft-only extensions) or to a particular hardware target's
intrinsics/attributes (SVE/SME/NEON/AVX/RISC-V-vector/AMDGPU…) are out of scope —
their being uncovered is expected, and they shouldn't count in the denominator
or live in the dataset.

Two signals: high-precision vendor **keywords** (``is_obviously_out_of_scope``)
and an **LLM judge** for the rest (``build_scope_prompt`` + ``parse_scope_verdicts``).
"""
from __future__ import annotations

import re
from typing import Optional

# Vendor/dialect/target tokens that unambiguously mark a non-C/C++ diagnostic.
# Matched as ``_tok`` / ``tok_`` word-ish fragments in the lowercased name to
# avoid false hits (e.g. "acc_" won't match "access").
_OUT_TOKENS = (
    "omp", "openmp", "acc_", "openacc", "opencl", "_ocl", "ocl_", "_cl_",
    "cuda", "hip_", "_hip", "sycl", "hlsl", "dxil", "shader",
    "objc", "_arc", "arc_", "nsobject", "nsstring", "nsnumber", "nsarray",
    "declspec", "dllimport", "dllexport", "uuidof", "_seh", "seh_", "ms_",
    "sve", "_sme", "sme_", "neon", "_mve", "mve_", "riscv", "rvv", "_rvv",
    "wasm", "altivec", "_vsx", "ppc_", "mips_", "amdgpu", "nvptx", "_spir",
    "spirv", "openacc", "hlsl", "wgsl",
)


def is_obviously_out_of_scope(name: str) -> bool:
    """True if the diagnostic name contains an unambiguous non-C/C++ vendor token."""
    nl = name.lower()
    return any(tok in nl for tok in _OUT_TOKENS)


_SCOPE_SYSTEM = (
    "You classify Clang diagnostics for a dataset of STANDARD C and C++ "
    "compilation errors. For each item (diagnostic name — message), answer IN if "
    "it is an error in standard ISO C or C++ code — including templates, "
    "constexpr, concepts, coroutines, modules, lambdas, and ordinary GNU/Clang "
    "extensions used in normal C/C++. Answer OUT if it is specific to a non-C/C++ "
    "dialect or a hardware target: Objective-C/C++, OpenMP, OpenACC, OpenCL, "
    "CUDA, HIP, SYCL, HLSL, Microsoft-only extensions, or a particular CPU "
    "target's intrinsics/attributes (SVE/SME/NEON/AVX/RISC-V vector/AMDGPU/etc.). "
    "Output exactly one line per item: '<number>: IN' or '<number>: OUT'."
)


def build_scope_prompt(items: list[tuple[str, str]]) -> list[dict]:
    """Chat messages asking the model to classify a batch of (name, message)."""
    lines = [f"{i + 1}. {name} — {msg}" for i, (name, msg) in enumerate(items)]
    return [
        {"role": "system", "content": _SCOPE_SYSTEM},
        {"role": "user", "content": "Classify each:\n" + "\n".join(lines)},
    ]


_VERDICT_RE = re.compile(r"(\d+)\s*[:.\)]\s*(IN|OUT)\b", re.IGNORECASE)


def parse_scope_verdicts(reply: str, n: int) -> dict[int, bool]:
    """Parse '<number>: IN/OUT' lines into ``{0-based index: in_scope}``.

    Out-of-range indices and unparseable lines are ignored; a missing index just
    means "no verdict" (caller decides the default).
    """
    out: dict[int, bool] = {}
    for m in _VERDICT_RE.finditer(reply):
        idx = int(m.group(1)) - 1
        if 0 <= idx < n:
            out[idx] = m.group(2).upper() == "IN"
    return out
