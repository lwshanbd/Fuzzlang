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


def build_pair_prompt(
    diag_name: str,
    msg_template: str,
    example: str,
    language: str = "c++",
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
        f"Now write a self-contained {language} program (no #include): "
        f"first the CORRECT version that compiles cleanly, then the BROKEN "
        f"version that triggers {diag_name}. Label them CORRECT and BROKEN, each "
        f"as a single fenced code block."
    )
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]
