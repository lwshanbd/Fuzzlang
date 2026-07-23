"""Index Clang source locations that emit typed diagnostics.

TableGen defines the diagnostic label and message.  Emission sites in Clang's
implementation provide the missing operational evidence: the parser or Sema
condition that causes the diagnostic to become primary.  The index is compact
and serializable so large local-model campaigns build it once and reuse it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Mapping, Sequence

from gen.realcorpus.corpus import is_test_path


_DIAG_REF = re.compile(r"\bdiag::([A-Za-z_]\w*)\b")
_SOURCE_SUFFIXES = frozenset({
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".inc",
})

EmissionSite = dict[str, object]
EmissionIndex = dict[str, tuple[EmissionSite, ...]]


def build_emission_index(
    clang_root: Path,
    *,
    context_lines: int = 2,
    max_sites_per_diagnostic: int = 2,
) -> EmissionIndex:
    """Collect bounded, non-test Clang source windows around ``diag::`` uses."""
    if context_lines < 0:
        raise ValueError("context_lines must be non-negative")
    if max_sites_per_diagnostic <= 0:
        raise ValueError("max_sites_per_diagnostic must be positive")
    root = Path(clang_root)
    result: dict[str, list[EmissionSite]] = {}
    for path in sorted(root.rglob("*")):
        if (
            not path.is_file()
            or path.suffix.lower() not in _SOURCE_SUFFIXES
            or is_test_path(path.relative_to(root).as_posix())
        ):
            continue
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError:
            continue
        relative = path.relative_to(root).as_posix()
        for line_index, line in enumerate(lines):
            names = tuple(dict.fromkeys(_DIAG_REF.findall(line)))
            for name in names:
                sites = result.setdefault(name, [])
                if len(sites) >= max_sites_per_diagnostic:
                    continue
                start = max(0, line_index - context_lines)
                end = min(len(lines), line_index + context_lines + 1)
                sites.append({
                    "path": relative,
                    "line": line_index + 1,
                    "snippet": "\n".join(lines[start:end]),
                })
    return {
        name: tuple(sites)
        for name, sites in sorted(result.items())
    }


def write_emission_index(
    path: Path,
    index: Mapping[str, Sequence[Mapping[str, object]]],
) -> None:
    """Write a deterministic reusable compiler-evidence index."""
    payload = {
        "schema": "fuzzlang.clang_emission_index.v1",
        "diagnostics": {
            name: [dict(site) for site in sites]
            for name, sites in sorted(index.items())
        },
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n")


def load_emission_index(path: Path) -> EmissionIndex:
    """Load and minimally validate a persisted compiler-evidence index."""
    value = json.loads(Path(path).read_text())
    if value.get("schema") != "fuzzlang.clang_emission_index.v1":
        raise ValueError("unsupported Clang emission-index schema")
    diagnostics = value.get("diagnostics")
    if not isinstance(diagnostics, dict):
        raise ValueError("emission index requires a diagnostics object")
    result: EmissionIndex = {}
    for name, sites in diagnostics.items():
        if not isinstance(name, str) or not isinstance(sites, list):
            raise ValueError("invalid emission-index diagnostic entry")
        normalized: list[EmissionSite] = []
        for site in sites:
            if (
                not isinstance(site, dict)
                or not isinstance(site.get("path"), str)
                or not isinstance(site.get("line"), int)
                or not isinstance(site.get("snippet"), str)
            ):
                raise ValueError(f"invalid emission site for {name}")
            normalized.append(dict(site))
        result[name] = tuple(normalized)
    return result


def emission_evidence_for(
    index: Mapping[str, Sequence[Mapping[str, object]]],
    diag_name: str,
) -> str | None:
    """Render bounded emission evidence for one model request."""
    sites = index.get(diag_name, ())
    if not sites:
        return None
    return "\n\n".join(
        f"{site['path']}:{site['line']}\n{site['snippet']}"
        for site in sites
    )
