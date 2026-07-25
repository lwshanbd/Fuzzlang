"""Recover compact trigger evidence from Clang regression tests.

Regression tests are never candidate dataset sources.  They are compiler
documentation: a matching ``expected-error`` line can tell synthesis what a
rare diagnostic's precondition looks like, while all emitted FuzzLang records
continue to originate from verified non-test translation units.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path


_PLACEHOLDER_RE = re.compile(
    r"%(?:[A-Za-z_]+(?:<[^>]*>)?\{.*?\}\d+(?:,\d+)*|[A-Za-z_]*\d+(?:,\d+)*)"
)
_MIN_FRAGMENT_CHARS = 12
_SEARCH_TIMEOUT_SECONDS = 5


def _literal_fragments(message: str) -> tuple[str, ...]:
    """Return stable message literals useful for locating ``expected-*`` text."""
    fragments = {
        " ".join(part.split())
        for part in _PLACEHOLDER_RE.split(message)
        if len(" ".join(part.split())) >= _MIN_FRAGMENT_CHARS
    }
    return tuple(sorted(fragments, key=lambda value: (-len(value), value)))


def _matching_paths(root: Path, fragment: str) -> tuple[Path, ...]:
    """Locate candidate test files using ripgrep without invoking a shell."""
    if shutil.which("rg") is None:
        return ()
    try:
        result = subprocess.run(
            ["rg", "-l", "-F", fragment, str(root)],
            check=False,
            capture_output=True,
            text=True,
            timeout=_SEARCH_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        # Prompt-only test evidence must never abort a generation campaign.
        return ()
    if result.returncode not in {0, 1}:
        return ()
    return tuple(Path(line) for line in result.stdout.splitlines() if line)


def _line_window(path: Path, fragment: str, *, root: Path) -> str | None:
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return None
    needle = " ".join(fragment.split())
    for index, line in enumerate(lines):
        if needle in " ".join(line.split()):
            start = max(0, index - 4)
            stop = min(len(lines), index + 5)
            try:
                label = path.relative_to(root).as_posix()
            except ValueError:
                label = path.name
            return label + ":\n" + "\n".join(lines[start:stop])
    return None


def regression_evidence_for(
    diagnostic_message: str,
    test_root: str | Path,
    *,
    max_examples: int = 2,
) -> str | None:
    """Return bounded regression-test context for one TableGen message.

    The result is prompt evidence only.  It intentionally contains no parsed
    source artifact, compile command, or provenance that could allow a test
    source to enter the clean-source or dataset pipeline.
    """
    if not diagnostic_message or max_examples <= 0:
        return None
    root = Path(test_root)
    if not root.is_dir():
        return None
    examples: list[str] = []
    seen_paths: set[Path] = set()
    for fragment in _literal_fragments(diagnostic_message):
        for path in _matching_paths(root, fragment):
            if path in seen_paths:
                continue
            seen_paths.add(path)
            window = _line_window(path, fragment, root=root)
            if window is None:
                continue
            examples.append(window)
            if len(examples) == max_examples:
                return "Regression-test trigger evidence (not a dataset source):\n" + "\n\n".join(examples)
    if examples:
        return "Regression-test trigger evidence (not a dataset source):\n" + "\n\n".join(examples)
    return None
