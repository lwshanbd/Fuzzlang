"""Turn legacy NatErr Stage-2 rows into verified canonical paired Records."""
from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Optional

from foundation.record import Origin, Provenance, Record, Split
from foundation.verifier.base import BaseVerifier
from gen.realcorpus.corpus import is_test_path


SourceAt = Callable[[Path, str, str], tuple[Optional[str], str]]


@dataclass(frozen=True)
class FormalizeResult:
    status: str
    record: Optional[Record] = None
    detail: str = ""


def git_source_at(
    checkout: Path, revision: str, repo_path: str
) -> tuple[Optional[str], str]:
    """Read ``revision:repo_path`` without changing the checkout or index."""
    try:
        result = subprocess.run(
            ["git", "show", f"{revision}:{repo_path}"],
            cwd=checkout,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30.0,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)
    if result.returncode != 0:
        detail = result.stderr.strip() or f"git show exited {result.returncode}"
        return None, detail[-1000:]
    return result.stdout, ""


def _valid_repo_path(path: object) -> bool:
    if not isinstance(path, str) or not path:
        return False
    normalized = path.replace("\\", "/")
    pure = PurePosixPath(normalized)
    return not pure.is_absolute() and ".." not in pure.parts


def _valid_compile_cmd(command: object) -> bool:
    return (
        isinstance(command, list)
        and bool(command)
        and all(isinstance(token, str) for token in command)
        and "__CLANG__" in command
        and "__SRC__" in command
    )


def _language(source_path: str) -> str:
    return "c" if source_path.lower().endswith((".c", ".m")) else "c++"


def _record_id(row: dict, predecessor_sha: str, source_path: str) -> str:
    existing = row.get("instance_id")
    if isinstance(existing, str) and existing:
        return existing
    project = row.get("project", "unknown")
    digest = hashlib.sha256(
        f"{project}|{predecessor_sha}|{source_path}".encode()
    ).hexdigest()[:12]
    return f"naterr-{digest}"


def _stderr_detail(prefix: str, stderr: str) -> str:
    compact = " ".join((stderr or "").split())
    return f"{prefix}: {compact[:1000]}" if compact else prefix


def formalize_row(
    row: dict,
    project_checkout: Path,
    verifier: BaseVerifier,
    *,
    source_at: SourceAt = git_source_at,
    expected_project: Optional[str] = None,
    split: Split = Split.EVAL,
) -> FormalizeResult:
    """Recover the fix side, revalidate both sides, and build a paired Record."""
    if not isinstance(row, dict):
        return FormalizeResult("invalid_row", detail="row is not a JSON object")

    project = row.get("project")
    if not isinstance(project, str) or not project:
        return FormalizeResult("missing_project", detail="project is required")
    if expected_project is not None and project != expected_project:
        return FormalizeResult(
            "project_mismatch", detail=f"expected {expected_project}, found {project}"
        )

    source_path = row.get("source_file") or row.get("source_path")
    if not _valid_repo_path(source_path):
        return FormalizeResult(
            "invalid_source_path", detail=f"invalid repository path: {source_path!r}"
        )
    source_path = source_path.replace("\\", "/")
    if is_test_path(source_path):
        return FormalizeResult("test_source", detail=source_path)

    predecessor_sha = row.get("commit_sha") or row.get("predecessor_sha")
    fix_sha = row.get("fix_sha")
    if not isinstance(predecessor_sha, str) or not predecessor_sha:
        return FormalizeResult(
            "missing_predecessor_sha", detail="commit_sha/predecessor_sha is required"
        )
    if not isinstance(fix_sha, str) or not fix_sha:
        return FormalizeResult("missing_fix_sha", detail="fix_sha is required")

    erroneous_src = row.get("buggy_src") or row.get("erroneous_src")
    if not isinstance(erroneous_src, str) or not erroneous_src:
        return FormalizeResult("missing_erroneous_src", detail="buggy_src is required")
    compile_cmd = row.get("compile_cmd")
    if not _valid_compile_cmd(compile_cmd):
        return FormalizeResult(
            "invalid_compile_cmd",
            detail="compile_cmd must contain string tokens __CLANG__ and __SRC__",
        )

    try:
        corrected_src, recovery_detail = source_at(
            Path(project_checkout), fix_sha, source_path
        )
    except Exception as exc:  # A custom repository backend is an audit boundary.
        return FormalizeResult("fixed_source_unavailable", detail=str(exc))
    if not isinstance(corrected_src, str) or not corrected_src:
        return FormalizeResult(
            "fixed_source_unavailable", detail=recovery_detail or "empty git object"
        )
    if corrected_src == erroneous_src:
        return FormalizeResult(
            "fix_does_not_change_source",
            detail=f"{fix_sha}:{source_path} equals predecessor source",
        )

    corrected = verifier.verify(
        corrected_src, compile_cmd, logical_path=source_path
    )
    if not corrected.ok:
        return FormalizeResult(
            "corrected_not_clean",
            detail=_stderr_detail("fix-side source does not compile", corrected.raw_stderr),
        )

    erroneous = verifier.verify(
        erroneous_src, compile_cmd, logical_path=source_path
    )
    if erroneous.ok:
        return FormalizeResult(
            "buggy_became_clean", detail="predecessor source now compiles cleanly"
        )
    if erroneous.diag is None:
        return FormalizeResult(
            "missing_primary_diagnostic",
            detail=_stderr_detail("no typed primary diagnostic", erroneous.raw_stderr),
        )

    expected_name = row.get("diag_name")
    expected_id = row.get("diag_id")
    observed = erroneous.diag
    name_drift = expected_name and observed.diag_name != expected_name
    id_drift = expected_id is not None and observed.diag_id != expected_id
    if name_drift or id_drift:
        return FormalizeResult(
            "diagnostic_drift",
            detail=(
                f"recorded=({expected_id!r}, {expected_name!r}), "
                f"observed=({observed.diag_id!r}, {observed.diag_name!r})"
            ),
        )

    detail = {
        "strategy": "naterr_commit_history",
        "project": project,
        "source_path": source_path,
        "predecessor_sha": predecessor_sha,
        "fix_sha": fix_sha,
        "compile_cmd": list(compile_cmd),
        "revalidated": True,
        "recorded_diag_id": expected_id,
        "recorded_diag_name": expected_name,
        "recorded_line": row.get("line"),
        "recorded_col": row.get("col"),
        "recorded_message": row.get("msg"),
    }
    for optional_key in ("commit_date_iso", "subject"):
        if optional_key in row:
            detail[optional_key] = row[optional_key]

    record = Record(
        record_id=_record_id(row, predecessor_sha, source_path),
        erroneous_src=erroneous_src,
        corrected_src=corrected_src,
        diagnostics=(observed,),
        provenance=Provenance(
            origin=Origin.REAL,
            source=f"{project}:{source_path}",
            detail=detail,
        ),
        split=split,
        language=_language(source_path),
    )
    return FormalizeResult("accepted", record=record)
