"""Parse Clang TableGen `.td` diagnostics into a catalog (coverage denominator).

A diagnostic is declared in a `.td` file as::

    def err_expected_semi_declaration : Error<"expected ';'">;
    def warn_x : Warning<"...">, InGroup<Group>, DefaultError;

The leading severity class (``Error`` / ``Warning`` / ``Extension`` / ``ExtWarn``
/ ``Remark`` / ``Note`` / ``Trap``) determines the kind. ``DefaultError``
promotes a warning to an error by default, so it counts as an error too.

The catalog gives us the authoritative set of error diagnostics for a fixed
LLVM version (the pinned `external/llvm-project` submodule). The numeric
``DiagID`` is assigned by the compiler at build time and is NOT in the `.td`;
coverage is therefore tracked by diagnostic *name*, and name-to-id mapping is
left to `diagtool` once the patched clang is built.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
# src/foundation/diagnostics/ -> repo root is three directories up.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
DEFAULT_BASIC_DIR = os.path.join(
    _REPO_ROOT, "external", "llvm-project", "clang", "include", "clang", "Basic"
)

# The severity classes a diagnostic `def` can lead with (see Diagnostic.td).
SEVERITY_CLASSES = frozenset(
    {"Error", "Warning", "Extension", "ExtWarn", "Remark", "Note", "Trap"}
)

_DEF_RE = re.compile(r"\bdef\s+([A-Za-z_][A-Za-z0-9_]*)\s*:")
_LEADING_CLASS_RE = re.compile(r"\s*([A-Za-z_]\w*)\s*<")
_INGROUP_RE = re.compile(r"\bInGroup<\s*([A-Za-z_]\w*)\s*>")
_DEFAULT_ERROR_RE = re.compile(r"\bDefaultError\b")
_STRING_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')


@dataclass(frozen=True)
class DiagEntry:
    """One diagnostic definition from the `.td` files."""

    name: str
    severity: str
    message: str
    component: Optional[str] = None
    in_group: Optional[str] = None
    default_error: bool = False

    @property
    def is_error(self) -> bool:
        """True if this diagnostic is an error by default."""
        return self.severity == "Error" or self.default_error


@dataclass
class Catalog:
    entries: list[DiagEntry] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.by_name: dict[str, DiagEntry] = {e.name: e for e in self.entries}

    def errors(self) -> list[DiagEntry]:
        return [e for e in self.entries if e.is_error]

    def names(self) -> list[str]:
        return [e.name for e in self.entries]

    def __len__(self) -> int:
        return len(self.entries)


def _strip_comments(text: str) -> str:
    """Remove `//` and `/* */` comments, leaving string literals intact."""
    out: list[str] = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            if j == -1:
                break
            i = j
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            if j == -1:
                break
            i = j + 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _read_body(text: str, start: int) -> str:
    """Read a `def` body from `start` (just after the colon) to the top-level `;`."""
    i, n = start, len(text)
    depth = 0
    in_str = False
    buf: list[str] = []
    while i < n:
        c = text[i]
        if in_str:
            buf.append(c)
            if c == "\\" and i + 1 < n:
                buf.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            buf.append(c)
            i += 1
            continue
        if c in "<([{":
            depth += 1
        elif c in ">)]}":
            depth -= 1
        elif c == ";" and depth == 0:
            return "".join(buf)
        buf.append(c)
        i += 1
    return "".join(buf)


def _balanced_angle(text: str, open_idx: int) -> str:
    """Return the content inside the `<...>` whose `<` is at `open_idx`."""
    i, n = open_idx, len(text)
    depth = 0
    in_str = False
    buf: list[str] = []
    while i < n:
        c = text[i]
        if in_str:
            buf.append(c)
            if c == "\\" and i + 1 < n:
                buf.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            buf.append(c)
            i += 1
            continue
        if c == "<":
            depth += 1
            if depth == 1:
                i += 1
                continue
        elif c == ">":
            depth -= 1
            if depth == 0:
                return "".join(buf)
        buf.append(c)
        i += 1
    return "".join(buf)


def _extract_message(angle_content: str) -> str:
    """Concatenate the string literals in a class's `<...>` into one message."""
    parts = _STRING_RE.findall(angle_content)
    return "".join(parts).replace('\\"', '"')


def parse_td_text(text: str, component: Optional[str] = None) -> list[DiagEntry]:
    """Parse all diagnostic definitions out of one `.td` text."""
    text = _strip_comments(text)
    entries: list[DiagEntry] = []
    for m in _DEF_RE.finditer(text):
        body = _read_body(text, m.end())
        cm = _LEADING_CLASS_RE.match(body)
        if not cm or cm.group(1) not in SEVERITY_CLASSES:
            continue
        severity = cm.group(1)
        message = _extract_message(_balanced_angle(body, cm.end() - 1))
        gm = _INGROUP_RE.search(body)
        entries.append(
            DiagEntry(
                name=m.group(1),
                severity=severity,
                message=message,
                component=component,
                in_group=gm.group(1) if gm else None,
                default_error=_DEFAULT_ERROR_RE.search(body) is not None,
            )
        )
    return entries


def _component_from_filename(path: str) -> Optional[str]:
    """`DiagnosticSemaKinds.td` -> `Sema`; non-Kinds files -> None."""
    m = re.match(r"Diagnostic(.*)Kinds\.td$", os.path.basename(path))
    return (m.group(1) or None) if m else None


def parse_td_file(path: str) -> list[DiagEntry]:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return parse_td_text(text, component=_component_from_filename(path))


def load_catalog(basic_dir: str = DEFAULT_BASIC_DIR) -> Catalog:
    """Load the catalog from every `Diagnostic*Kinds.td` in `basic_dir`."""
    entries: list[DiagEntry] = []
    for fn in sorted(os.listdir(basic_dir)):
        if fn.startswith("Diagnostic") and fn.endswith("Kinds.td"):
            entries.extend(parse_td_file(os.path.join(basic_dir, fn)))
    return Catalog(entries)
