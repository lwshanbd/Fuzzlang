"""Build the LLM prompt for guided correct/broken pair generation."""
from __future__ import annotations

_SYSTEM = (
    "You generate training pairs for a compiler-error-repair dataset. Given a "
    "target Clang diagnostic and an example program that triggers it, write a "
    "fresh, self-contained program in a DIFFERENT scenario, in two versions: a "
    "CORRECT one that compiles cleanly, and a BROKEN one that triggers the same "
    "diagnostic. Output exactly two fenced code blocks — the CORRECT version "
    "first, then the BROKEN version — and nothing else inside the blocks (no "
    "prose, no #include)."
)


_FEATURE_HINTS = [
    (("omp",), "This is an OpenMP diagnostic — use OpenMP directives (#pragma omp)."),
    (("arc",), "This is an Objective-C ARC diagnostic — write Objective-C under ARC."),
    (("objc",), "This is an Objective-C diagnostic — write Objective-C."),
    (("hlsl",), "This is an HLSL diagnostic — write HLSL shader code."),
    (("opencl", "ocl"), "This is an OpenCL diagnostic — write an OpenCL kernel."),
    (("coro",), "This is a C++20 coroutines diagnostic — use co_await/co_yield/co_return."),
    (("block",), "This is a Clang blocks diagnostic — use a ^{ } block."),
    (("module",), "This is a modules diagnostic — use import/module declarations."),
    (("matrix",), "This is a matrix-types diagnostic — use __attribute__((matrix_type))."),
    (("fixed_point", "fixedpoint"), "This is a fixed-point diagnostic — use _Accum/_Fract types."),
    (("sve", "sme", "neon", "riscv", "altivec", "wasm"),
     "This is a target-feature diagnostic — use the relevant target intrinsics/attributes."),
]


def feature_hint(diag_name: str) -> str:
    """Return an instruction to steer the model toward a feature-gated diagnostic,
    or "" if the name implies no particular feature."""
    nl = diag_name.lower()
    for keys, hint in _FEATURE_HINTS:
        if any(k in nl for k in keys):
            return hint
    return ""


def build_pair_prompt(
    diag_name: str,
    msg_template: str,
    example: str,
    language: str = "c++",
    extra: str = "",
) -> list[dict]:
    """Return chat messages asking for a correct/broken pair for `diag_name`.

    `example` is optional: when empty (e.g. a catalog diagnostic we never mined a
    snippet for), the model works from the diagnostic name and message template
    alone.
    """
    example_block = (
        f"Example program that triggers it:\n```\n{example}\n```\n\n"
        if example.strip() else
        "No example is provided — infer a triggering construct from the "
        "diagnostic name and message.\n\n"
    )
    user = (
        f"Target diagnostic: {diag_name}\n"
        f"Message template: {msg_template}\n"
        f"Language: {language}\n\n"
        f"{example_block}"
        f"{extra + chr(10) + chr(10) if extra else ''}"
        f"Now write a self-contained {language} program (no #include): "
        f"first the CORRECT version that compiles cleanly, then the BROKEN "
        f"version that triggers {diag_name}. Label them CORRECT and BROKEN, each "
        f"as a single fenced code block."
    )
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]
