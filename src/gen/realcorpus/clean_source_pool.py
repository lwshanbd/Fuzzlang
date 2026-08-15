"""Materialize a verified-clean, production-only translation-unit pool.

The pool is deliberately *not* a dataset.  Its rows contain only correct
source, its original compile command, and a content hash.  A generation
campaign may consume the rows later; only successfully verified edits become
paired :class:`foundation.record.Record` objects.
"""
from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from foundation.compile_db import build_clang_argv
from foundation.record import Record
from foundation.verifier.base import BaseVerifier
from gen.realcorpus.corpus import is_test_path, is_vendored_path, sanitize_cmd
from gen.realcorpus.finalize import portable_source_path


CLEAN_SOURCE_TU_SCHEMA = "fuzzlang.clean_source_tu"
CLEAN_SOURCE_TU_VERSION = 1
_SOURCE_EXTENSIONS = (".c", ".cc", ".cpp", ".cxx", ".c++", ".m", ".mm")


def _source_sha256(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _language_for_path(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix == ".m":
        return "objective-c"
    if suffix == ".mm":
        return "objective-c++"
    return "c" if suffix == ".c" else "c++"


def _valid_compile_cmd(value: Sequence[str]) -> bool:
    return (
        bool(value)
        and all(isinstance(item, str) for item in value)
        and "__CLANG__" in value
        and "__SRC__" in value
    )


@dataclass(frozen=True)
class CleanSourceTU:
    """One verified-clean, non-test translation unit available for replay."""

    source_id: str
    project: str
    source_path: str
    language: str
    corrected_src: str
    compile_cmd: tuple[str, ...]
    source_sha256: str
    baseline_compiler: str

    def __post_init__(self) -> None:
        if not isinstance(self.project, str) or not self.project:
            raise ValueError("project must be non-empty")
        if not isinstance(self.source_path, str) or not self.source_path:
            raise ValueError("source_path must be non-empty")
        if self.source_path.startswith(("/", "\\")) or ".." in self.source_path.split("/"):
            raise ValueError("source_path must be project-relative")
        expected_id = f"{self.project}:{self.source_path}"
        if self.source_id != expected_id:
            raise ValueError("source_id must equal project:source_path")
        if is_test_path(self.source_path) or is_test_path(self.source_id):
            raise ValueError("test/example/benchmark/fuzzer paths are forbidden")
        if is_vendored_path(self.source_path):
            # A vendored dependency carries another project's source under this
            # project's name, which silently breaks held-out project isolation.
            raise ValueError("vendored/generated third-party paths are forbidden")
        if self.language not in ("c", "c++", "objective-c", "objective-c++"):
            raise ValueError(
                "language must be 'c', 'c++', 'objective-c', or 'objective-c++'",
            )
        if not isinstance(self.corrected_src, str) or not self.corrected_src:
            raise ValueError("corrected_src must be non-empty")
        if not isinstance(self.compile_cmd, tuple):
            object.__setattr__(self, "compile_cmd", tuple(self.compile_cmd))
        if not _valid_compile_cmd(self.compile_cmd):
            raise ValueError("compile_cmd must contain __CLANG__ and __SRC__ placeholders")
        expected_hash = _source_sha256(self.corrected_src)
        if self.source_sha256 != expected_hash:
            raise ValueError("source_sha256 does not match corrected_src")
        if not isinstance(self.baseline_compiler, str) or not self.baseline_compiler:
            raise ValueError("baseline_compiler must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CLEAN_SOURCE_TU_SCHEMA,
            "schema_version": CLEAN_SOURCE_TU_VERSION,
            "source_id": self.source_id,
            "project": self.project,
            "source_path": self.source_path,
            "language": self.language,
            "corrected_src": self.corrected_src,
            "compile_cmd": list(self.compile_cmd),
            "source_sha256": self.source_sha256,
            "baseline_compiler": self.baseline_compiler,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CleanSourceTU":
        if value.get("schema") != CLEAN_SOURCE_TU_SCHEMA:
            raise ValueError("unrecognized clean source schema")
        if value.get("schema_version") != CLEAN_SOURCE_TU_VERSION:
            raise ValueError("unsupported clean source schema_version")
        compile_cmd = value.get("compile_cmd")
        if not isinstance(compile_cmd, list):
            raise ValueError("compile_cmd must be a list")
        return cls(
            source_id=value["source_id"],
            project=value["project"],
            source_path=value["source_path"],
            language=value["language"],
            corrected_src=value["corrected_src"],
            compile_cmd=tuple(compile_cmd),
            source_sha256=value["source_sha256"],
            baseline_compiler=value["baseline_compiler"],
        )


@dataclass(frozen=True)
class CleanSourceRejection:
    status: str
    source_id: str
    source_path: str
    detail: str | None = None
    observed_diag: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "status": self.status,
            "source_id": self.source_id,
            "source_path": self.source_path,
        }
        if self.detail is not None:
            value["detail"] = self.detail
        if self.observed_diag is not None:
            value["observed_diag"] = self.observed_diag
        return value


@dataclass(frozen=True)
class CleanSourcePoolResult:
    sources: tuple[CleanSourceTU, ...]
    rejections: tuple[CleanSourceRejection, ...]
    counts: Mapping[str, int]


def load_clean_sources_jsonl(path: str | Path) -> list[CleanSourceTU]:
    """Load strict clean-source rows with line-numbered errors."""
    result: list[CleanSourceTU] = []
    for line_number, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("row must be a JSON object")
            result.append(CleanSourceTU.from_dict(value))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError(f"{path}:{line_number}: invalid CleanSourceTU: {error}") from error
    return result


_STANDARD_FLAG_RE = re.compile(r"^(?P<prefix>--?std=)(?P<standard>(?:gnu\+\+|c\+\+|gnu|c).+)$")
_CPP_STANDARD_RE = re.compile(r"^(?:gnu\+\+|c\+\+)\d[a-z0-9]*$")
_C_STANDARD_RE = re.compile(r"^(?:gnu|c)(?:89|90|99|11|17|23|2x|2y)$")


def _standard_family(language: str) -> str:
    """Return the C or C++ standard family for a frontend language mode."""
    if language in {"c", "objective-c"}:
        return "c"
    if language in {"c++", "objective-c++"}:
        return "c++"
    raise ValueError(f"unsupported FuzzLang source language: {language!r}")


def _with_standard(
    command: Sequence[str], *, language: str, standard: str,
) -> tuple[str, ...]:
    """Replace (or add) one language-standard flag in a clean-pool command."""
    family = _standard_family(language)
    matcher = _CPP_STANDARD_RE if family == "c++" else _C_STANDARD_RE
    if not matcher.fullmatch(standard):
        raise ValueError(f"standard {standard!r} is invalid for language {language!r}")
    result: list[str] = []
    replaced = False
    for argument in command:
        match = _STANDARD_FLAG_RE.fullmatch(argument)
        is_cpp_flag = match is not None and "++" in match.group("standard")
        if match is None or (family == "c++") != is_cpp_flag:
            result.append(argument)
            continue
        if not replaced:
            result.append(f"{match.group('prefix')}{standard}")
            replaced = True
    if not replaced:
        try:
            insertion = result.index("__CLANG__") + 1
        except ValueError as error:  # CleanSourceTU already protects this invariant.
            raise ValueError("compile command lacks __CLANG__") from error
        result.insert(insertion, f"-std={standard}")
    return tuple(result)


def _with_extra_args(command: Sequence[str], extra_args: Sequence[str]) -> tuple[str, ...]:
    """Insert validated compile-mode flags immediately before the source slot."""
    values = tuple(extra_args)
    if any(not isinstance(value, str) or not value or value == "__SRC__" for value in values):
        raise ValueError("extra_args must be non-empty strings and cannot contain __SRC__")
    if not values:
        return tuple(command)
    try:
        source_index = tuple(command).index("__SRC__")
    except ValueError as error:  # CleanSourceTU already protects this invariant.
        raise ValueError("compile command lacks __SRC__") from error
    return tuple(command[:source_index]) + values + tuple(command[source_index:])


def revalidate_standard_pool(
    sources: Iterable[CleanSourceTU],
    verifier: BaseVerifier,
    *,
    language: str,
    standard: str,
    extra_args: Sequence[str] = (),
    workers: int = 8,
) -> CleanSourcePoolResult:
    """Create a clean real-source pool under a distinct language standard.

    This does not modify source text or its production provenance.  It only
    substitutes the language-standard compiler flag, then clean-gates every
    parent again before it can be used by a mode-specific Injector campaign.
    """
    if workers <= 0:
        raise ValueError("workers must be positive")
    # Validate before scheduling work, including when the input is empty.
    family = _standard_family(language)
    matcher = _CPP_STANDARD_RE if family == "c++" else _C_STANDARD_RE
    if not matcher.fullmatch(standard):
        raise ValueError(f"standard {standard!r} is invalid for language {language!r}")
    values = tuple(sources)
    candidates = [source for source in values if source.language == language]
    other_language_sources = sum(1 for source in values if source.language != language)

    def process(source: CleanSourceTU):
        command = _with_extra_args(
            _with_standard(source.compile_cmd, language=language, standard=standard),
            extra_args,
        )
        try:
            result = verifier.verify(
                source.corrected_src, list(command), logical_path=source.source_path,
            )
        except Exception as error:
            return None, CleanSourceRejection(
                "retargeted_verifier_error", source.source_id, source.source_path,
                f"{type(error).__name__}: {error}",
            )
        if not result.ok:
            return None, CleanSourceRejection(
                "retargeted_not_clean", source.source_id, source.source_path,
                observed_diag=(result.diag.diag_name if result.diag else None),
            )
        return replace(source, compile_cmd=command), None

    accepted: list[CleanSourceTU] = []
    rejections: list[CleanSourceRejection] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for source, rejection in executor.map(process, candidates):
            if source is not None:
                accepted.append(source)
            elif rejection is not None:
                rejections.append(rejection)
    return CleanSourcePoolResult(
        sources=tuple(accepted),
        rejections=tuple(rejections),
        counts={
            "input_clean_sources": len(candidates) + other_language_sources,
            "non_target_language_sources": other_language_sources,
            "attempted_clean_gates": len(candidates),
            "accepted_clean_sources": len(accepted),
        },
    )


def revalidate_cpp_standard_pool(
    sources: Iterable[CleanSourceTU],
    verifier: BaseVerifier,
    *,
    standard: str,
    extra_args: Sequence[str] = (),
    workers: int = 8,
) -> CleanSourcePoolResult:
    """Backward-compatible C++ wrapper for :func:`revalidate_standard_pool`."""
    result = revalidate_standard_pool(
        sources, verifier, language="c++", standard=standard,
        extra_args=extra_args, workers=workers,
    )
    counts = dict(result.counts)
    counts["non_cpp_sources"] = counts.pop("non_target_language_sources")
    return CleanSourcePoolResult(
        sources=result.sources, rejections=result.rejections, counts=counts,
    )


def build_clean_source_pool(
    compile_db: Mapping[str, Mapping[str, Any]],
    verifier: BaseVerifier,
    *,
    project: str,
    source_root: str | None,
    source_substr: str | None = None,
    excluded_source_ids: Iterable[str] = (),
    max_files: int | None = None,
    workers: int = 8,
    baseline_compiler: str = "llvmorg-22.1.8",
) -> CleanSourcePoolResult:
    """Clean-gate deterministic, unseen production TUs from a compile database."""
    if not project:
        raise ValueError("project must be non-empty")
    if max_files is not None and max_files < 0:
        raise ValueError("max_files must be non-negative or None")
    if workers <= 0:
        raise ValueError("workers must be positive")
    excluded = set(excluded_source_ids)
    candidates: list[tuple[str, str, str]] = []
    test_sources = 0
    vendored_sources = 0
    excluded_known_sources = 0
    source_candidates = 0
    for raw_path in sorted(compile_db):
        lower = raw_path.lower()
        if not lower.endswith(_SOURCE_EXTENSIONS):
            continue
        if source_substr and source_substr not in raw_path:
            continue
        if is_test_path(raw_path):
            test_sources += 1
            continue
        if is_vendored_path(portable_source_path(raw_path, source_root=source_root)):
            vendored_sources += 1
            continue
        source_candidates += 1
        logical_path = portable_source_path(raw_path, source_root=source_root)
        source_id = f"{project}:{logical_path}"
        if source_id in excluded:
            excluded_known_sources += 1
            continue
        candidates.append((raw_path, logical_path, source_id))
    if max_files is not None:
        candidates = candidates[:max_files]

    def process(item: tuple[str, str, str]):
        raw_path, logical_path, source_id = item
        try:
            corrected_src = Path(raw_path).read_text(errors="replace")
        except OSError as error:
            return None, CleanSourceRejection(
                "source_read_failed", source_id, logical_path, str(error),
            )
        try:
            compile_cmd = tuple(sanitize_cmd(build_clang_argv(
                dict(compile_db[raw_path]), "__CLANG__", "__SRC__",
            )))
            baseline = verifier.verify(
                corrected_src, list(compile_cmd), logical_path=logical_path,
            )
        except Exception as error:  # retain an audit trail for long campaigns
            return None, CleanSourceRejection(
                "baseline_verifier_error", source_id, logical_path,
                f"{type(error).__name__}: {error}",
            )
        if not baseline.ok:
            return None, CleanSourceRejection(
                "corrected_not_clean", source_id, logical_path,
                observed_diag=(baseline.diag.diag_name if baseline.diag else None),
            )
        return CleanSourceTU(
            source_id=source_id,
            project=project,
            source_path=logical_path,
            language=_language_for_path(raw_path),
            corrected_src=corrected_src,
            compile_cmd=compile_cmd,
            source_sha256=_source_sha256(corrected_src),
            baseline_compiler=baseline_compiler,
        ), None

    sources: list[CleanSourceTU] = []
    rejections: list[CleanSourceRejection] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for source, rejection in executor.map(process, candidates):
            if source is not None:
                sources.append(source)
            elif rejection is not None:
                rejections.append(rejection)
    return CleanSourcePoolResult(
        sources=tuple(sources),
        rejections=tuple(rejections),
        counts={
            "compile_db_entries": len(compile_db),
            "source_candidates": source_candidates,
            "excluded_known_sources": excluded_known_sources,
            "test_sources": test_sources,
            "vendored_sources": vendored_sources,
            "attempted_clean_gates": len(candidates),
            "accepted_clean_sources": len(sources),
        },
    )


def build_clean_source_pool_from_records(
    records: Iterable[Record],
    verifier: BaseVerifier,
    *,
    project: str,
    excluded_source_ids: Iterable[str] = (),
    max_files: int | None = None,
    workers: int = 8,
    baseline_compiler: str = "llvmorg-22.1.8",
) -> CleanSourcePoolResult:
    """Revalidate correct parents archived in paired real-source records.

    This lets a prior paired corpus seed a new, *clean-only* source pool for a
    later campaign without trusting its historical compiler result.  Each
    source is deduplicated by its stable ``project:path`` identity and passed
    through the current verifier before it becomes a :class:`CleanSourceTU`.
    The original compile command is retained only when it already uses the
    placeholders required by the clean-pool schema.
    """
    if not project:
        raise ValueError("project must be non-empty")
    if max_files is not None and max_files < 0:
        raise ValueError("max_files must be non-negative or None")
    if workers <= 0:
        raise ValueError("workers must be positive")

    prefix = f"{project}:"
    excluded = set(excluded_source_ids)
    candidates: dict[str, tuple[str, str, str, tuple[str, ...]]] = {}
    rejections: list[CleanSourceRejection] = []
    counts: dict[str, int] = {
        "record_candidates": 0,
        "matching_project_records": 0,
        "unique_source_candidates": 0,
        "duplicate_parent_records": 0,
        "test_sources": 0,
        "vendored_sources": 0,
        "invalid_record_provenance": 0,
        "excluded_known_sources": 0,
    }

    for record in records:
        counts["record_candidates"] += 1
        source_id = record.provenance.source
        if not source_id.startswith(prefix):
            continue
        counts["matching_project_records"] += 1
        detail = record.provenance.detail
        path = detail.get("source_path") if isinstance(detail, dict) else None
        command = detail.get("compile_cmd") if isinstance(detail, dict) else None
        expected_path = source_id[len(prefix):]
        if (
            not isinstance(path, str)
            or not path
            or path != expected_path
            or not isinstance(command, list)
            or not _valid_compile_cmd(command)
            or not record.corrected_src
            or record.language not in ("c", "c++", "objective-c", "objective-c++")
        ):
            counts["invalid_record_provenance"] += 1
            rejections.append(CleanSourceRejection(
                "invalid_record_provenance", source_id,
                path if isinstance(path, str) and path else expected_path,
            ))
            continue
        if is_test_path(path) or is_test_path(source_id):
            counts["test_sources"] += 1
            continue
        if is_vendored_path(path):
            counts["vendored_sources"] = counts.get("vendored_sources", 0) + 1
            continue
        candidate = (path, record.language, record.corrected_src, tuple(command))
        previous = candidates.get(source_id)
        if previous is not None:
            if previous == candidate:
                counts["duplicate_parent_records"] += 1
            else:
                counts["invalid_record_provenance"] += 1
                rejections.append(CleanSourceRejection(
                    "conflicting_parent_snapshot", source_id, path,
                ))
            continue
        candidates[source_id] = candidate

    counts["unique_source_candidates"] = len(candidates)
    scheduled: list[tuple[str, str, str, str, tuple[str, ...]]] = []
    for source_id, (path, language, corrected_src, command) in sorted(candidates.items()):
        if source_id in excluded:
            counts["excluded_known_sources"] += 1
            continue
        scheduled.append((source_id, path, language, corrected_src, command))
    if max_files is not None:
        scheduled = scheduled[:max_files]

    def process(item: tuple[str, str, str, str, tuple[str, ...]]):
        source_id, path, language, corrected_src, command = item
        try:
            baseline = verifier.verify(
                corrected_src, list(command), logical_path=path,
            )
        except Exception as error:  # retain a source-specific audit trail
            return None, CleanSourceRejection(
                "baseline_verifier_error", source_id, path,
                f"{type(error).__name__}: {error}",
            )
        if not baseline.ok:
            return None, CleanSourceRejection(
                "corrected_not_clean", source_id, path,
                observed_diag=(baseline.diag.diag_name if baseline.diag else None),
            )
        return CleanSourceTU(
            source_id=source_id,
            project=project,
            source_path=path,
            language=language,
            corrected_src=corrected_src,
            compile_cmd=command,
            source_sha256=_source_sha256(corrected_src),
            baseline_compiler=baseline_compiler,
        ), None

    sources: list[CleanSourceTU] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for source, rejection in executor.map(process, scheduled):
            if source is not None:
                sources.append(source)
            elif rejection is not None:
                rejections.append(rejection)
    counts["attempted_clean_gates"] = len(scheduled)
    counts["accepted_clean_sources"] = len(sources)
    return CleanSourcePoolResult(
        sources=tuple(sources),
        rejections=tuple(rejections),
        counts=counts,
    )
