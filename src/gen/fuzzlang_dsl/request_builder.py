"""Build compiler-evidence synthesis requests from real clean source TUs.

Archived learned recipes are used only as a *retrieval seed*: they identify a
diagnostic/syntax shape worth asking the model about and locate real production
snippets where that shape occurs.  The recipe edit itself is deliberately not
included in the resulting :class:`SynthesisRequest` or the model prompt.  The
local model must independently synthesize a FuzzLang DSL Injector from the
compiler diagnostic evidence and correct code snippets.
"""
from __future__ import annotations

import json
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

from foundation.diagnostics.catalog import Catalog, DiagEntry
from gen.fuzzlang_dsl.synthesis import DiagnosticEvidence, SynthesisRequest
from gen.realcorpus.clean_source_pool import CleanSourceTU
from gen.realcorpus.recipes import LearnedRecipe, apply_recipe


@dataclass(frozen=True)
class RequestBuildAudit:
    """One target's reproducible request-selection outcome."""

    diag_name: str
    status: str
    recipe_id: Optional[str] = None
    source_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "diag_name": self.diag_name,
            "status": self.status,
        }
        if self.recipe_id is not None:
            value["retrieval_recipe_id"] = self.recipe_id
        if self.source_ids:
            value["source_ids"] = list(self.source_ids)
        return value


@dataclass(frozen=True)
class RequestBuildResult:
    """Model-ready requests plus an audit row for every considered target."""

    requests: tuple[SynthesisRequest, ...]
    audits: tuple[RequestBuildAudit, ...]


def request_to_dict(request: SynthesisRequest) -> dict[str, object]:
    """Serialize a request without leaking retrieval-recipe edit semantics."""
    return {
        "diag_name": request.diag_name,
        "diag_id": request.diag_id,
        "diag_message": request.diag_message,
        "component": request.component,
        "language": request.language,
        "tablegen_definition": request.evidence.tablegen_definition,
        "emission_evidence": request.evidence.emission_evidence,
        "correct_snippets": list(request.correct_snippets),
        "single_witness_long_tail": request.single_witness_long_tail,
    }


def request_to_json(request: SynthesisRequest) -> str:
    """Return one canonical JSONL row."""
    return json.dumps(request_to_dict(request), ensure_ascii=False, sort_keys=True)


def resolve_diag_ids(
    diag_names: Iterable[str],
    diagtool_bin: str,
    *,
    runner=subprocess.run,
) -> dict[str, int]:
    """Resolve compiler-assigned IDs with the pinned patched-clang diagtool.

    A missing lookup is intentionally omitted rather than guessed; callers may
    still construct a name-only request, but the production CLI records the
    missing mapping in its audit manifest.
    """
    resolved: dict[str, int] = {}
    for name in sorted(set(diag_names)):
        completed = runner(
            [diagtool_bin, "find-diagnostic-id", name],
            check=False,
            capture_output=True,
            text=True,
        )
        value = completed.stdout.strip()
        if completed.returncode == 0 and value.isdecimal():
            resolved[name] = int(value)
    return resolved


def _normalized_tablegen_definition(entry: DiagEntry) -> str:
    """Return a compiler-catalog-derived, self-contained TableGen summary."""
    suffix = ", DefaultError" if entry.default_error else ""
    return (
        f"def {entry.name} : {entry.severity}<"
        f"{json.dumps(entry.message, ensure_ascii=False)}>{suffix};"
    )


def _snippet_around(source: str, start: int, end: int, *, radius: int) -> str:
    """Take a bounded line-aligned excerpt while retaining the matched tokens."""
    anchor_end = max(start + 1, end)
    left_limit = max(0, start - radius)
    begin = source.rfind("\n", 0, left_limit) + 1
    right_limit = min(len(source), anchor_end + radius)
    newline = source.find("\n", right_limit)
    finish = len(source) if newline < 0 else newline + 1
    return source[begin:finish].strip()


def _find_real_snippets(
    recipe: LearnedRecipe,
    clean_sources: Iterable[CleanSourceTU],
    *,
    count: int,
    radius: int,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    snippets: list[str] = []
    source_ids: list[str] = []
    for source in sorted(clean_sources, key=lambda item: item.source_id):
        if source.language != recipe.language:
            continue
        applications = apply_recipe(
            source.corrected_src,
            recipe,
            max_candidates=1,
        )
        if not applications:
            continue
        application = applications[0]
        snippet = _snippet_around(
            source.corrected_src,
            application.start,
            application.end,
            radius=radius,
        )
        if not snippet:
            continue
        snippets.append(snippet)
        source_ids.append(source.source_id)
        if len(snippets) == count:
            break
    return tuple(snippets), tuple(source_ids)


def build_synthesis_requests(
    recipes: Iterable[LearnedRecipe],
    clean_sources: Iterable[CleanSourceTU],
    catalog: Catalog,
    *,
    covered_diag_names: Iterable[str] = (),
    eligible_diag_names: Iterable[str] | None = None,
    diag_ids: Mapping[str, int] | None = None,
    max_targets: int,
    snippets_per_target: int = 2,
    snippet_radius: int = 240,
) -> RequestBuildResult:
    """Select uncovered error targets and retrieve matching real code snippets.

    This function never emits a mutation or an Injector.  It uses only the
    lexical *match* of an archived portable recipe to retrieve clean production
    code.  Consequently, the model prompt contains compiler evidence and real
    correct snippets, but neither a prior erroneous source nor a recipe edit.
    """
    if max_targets < 0:
        raise ValueError("max_targets must be non-negative")
    if not 2 <= snippets_per_target <= 5:
        raise ValueError("snippets_per_target must be between 2 and 5")
    if snippet_radius <= 0:
        raise ValueError("snippet_radius must be positive")

    covered = set(covered_diag_names)
    eligible = None if eligible_diag_names is None else set(eligible_diag_names)
    ids = dict(diag_ids or {})
    grouped: dict[str, list[LearnedRecipe]] = defaultdict(list)
    for recipe in recipes:
        grouped[recipe.diag_name].append(recipe)
    sources = tuple(clean_sources)
    ordered_names = sorted(
        grouped,
        key=lambda name: (-max(recipe.support for recipe in grouped[name]), name),
    )

    requests: list[SynthesisRequest] = []
    audits: list[RequestBuildAudit] = []
    for name in ordered_names:
        candidates = grouped[name]
        if eligible is not None and name not in eligible:
            audits.append(RequestBuildAudit(name, "skipped_not_gap"))
            continue
        if name in covered:
            audits.append(RequestBuildAudit(name, "skipped_covered"))
            continue
        entry = catalog.by_name.get(name)
        if entry is None or not entry.is_error:
            audits.append(RequestBuildAudit(name, "skipped_not_catalog_error"))
            continue
        portable = sorted(
            (recipe for recipe in candidates if recipe.portable),
            key=lambda recipe: (-recipe.support, recipe.recipe_id),
        )
        if not portable:
            audits.append(RequestBuildAudit(name, "skipped_no_portable_recipe"))
            continue
        if len(requests) >= max_targets:
            audits.append(RequestBuildAudit(name, "deferred_max_targets"))
            continue

        selected: Optional[tuple[LearnedRecipe, tuple[str, ...], tuple[str, ...]]] = None
        for recipe in portable:
            snippets, source_ids = _find_real_snippets(
                recipe,
                sources,
                count=snippets_per_target,
                radius=snippet_radius,
            )
            if len(snippets) == snippets_per_target:
                selected = recipe, snippets, source_ids
                break
        if selected is None:
            audits.append(RequestBuildAudit(
                name,
                "skipped_no_two_real_snippets",
                recipe_id=portable[0].recipe_id,
            ))
            continue

        recipe, snippets, source_ids = selected
        diag_id = ids.get(name)
        if diag_id is not None and (
            isinstance(diag_id, bool) or not isinstance(diag_id, int) or diag_id < 0
        ):
            raise ValueError(f"invalid diagnostic id for {name}")
        requests.append(SynthesisRequest(
            diag_name=name,
            diag_id=diag_id,
            diag_message=entry.message,
            component=entry.component or "Unknown",
            language=recipe.language,
            correct_snippets=snippets,
            evidence=DiagnosticEvidence(
                tablegen_definition=_normalized_tablegen_definition(entry),
            ),
        ))
        audits.append(RequestBuildAudit(
            name,
            "selected",
            recipe_id=recipe.recipe_id,
            source_ids=source_ids,
        ))
    return RequestBuildResult(tuple(requests), tuple(audits))
