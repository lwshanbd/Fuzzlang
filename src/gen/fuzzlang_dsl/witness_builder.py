"""Build model requests with compiler-validated, non-dataset trigger witnesses.

Portable learned recipes are used only as an internal retrieval and witness
discovery aid.  A recipe may supply a candidate mutation of clean production
code, but that candidate is recompiled with the pinned verifier before it is
allowed to influence a model request.  The model receives the resulting bounded
code window as compiler evidence, never a recipe identifier or recipe object.

The witness is *not* a dataset record.  Later replay independently clean-gates
the parent and accepts only a new exact-target pair, preserving the core
FuzzLang provenance rule.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

from foundation.diagnostics.catalog import Catalog, DiagEntry
from foundation.verifier.base import BaseVerifier
from gen.fuzzlang_dsl.request_builder import _normalized_tablegen_definition, _snippet_around
from gen.fuzzlang_dsl.synthesis import DiagnosticEvidence, SynthesisRequest
from gen.realcorpus.clean_source_pool import CleanSourceTU
from gen.realcorpus.recipes import LearnedRecipe, apply_recipe


@dataclass(frozen=True)
class WitnessBuildAudit:
    """One target's reproducible witness-request selection outcome."""

    diag_name: str
    status: str
    recipe_id: Optional[str] = None
    source_ids: tuple[str, ...] = ()
    witness_source_id: Optional[str] = None
    observed_diag: Optional[str] = None

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "diag_name": self.diag_name,
            "status": self.status,
        }
        if self.recipe_id is not None:
            value["retrieval_recipe_id"] = self.recipe_id
        if self.source_ids:
            value["source_ids"] = list(self.source_ids)
        if self.witness_source_id is not None:
            value["witness_source_id"] = self.witness_source_id
        if self.observed_diag is not None:
            value["observed_diag"] = self.observed_diag
        return value


@dataclass(frozen=True)
class WitnessBuildResult:
    """Validated evidence requests plus one audit row per considered target."""

    requests: tuple[SynthesisRequest, ...]
    audits: tuple[WitnessBuildAudit, ...]


@dataclass(frozen=True)
class _TriggerWitness:
    source_id: str
    mutated_snippet: str


def _find_real_snippets(
    recipe: LearnedRecipe,
    sources: Iterable[CleanSourceTU],
    *,
    count: int,
    radius: int,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    snippets: list[str] = []
    source_ids: list[str] = []
    for source in sources:
        if source.language != recipe.language:
            continue
        applications = apply_recipe(source.corrected_src, recipe, max_candidates=1)
        if not applications:
            continue
        application = applications[0]
        snippet = _snippet_around(
            source.corrected_src, application.start, application.end, radius=radius,
        )
        if not snippet:
            continue
        snippets.append(snippet)
        source_ids.append(source.source_id)
        if len(snippets) == count:
            break
    return tuple(snippets), tuple(source_ids)


def _target_matches(
    *,
    target_name: str,
    target_id: Optional[int],
    observed_name: Optional[str],
    observed_id: Optional[int],
) -> bool:
    return observed_name == target_name and (
        target_id is None or observed_id == target_id
    )


def _find_compiler_witness(
    recipe: LearnedRecipe,
    sources: Iterable[CleanSourceTU],
    verifier: BaseVerifier,
    *,
    target_name: str,
    target_id: Optional[int],
    clean_cache: dict[str, bool],
    radius: int,
    max_candidates_per_source: int,
) -> tuple[Optional[_TriggerWitness], Optional[str]]:
    """Return the first clean-parent compiler-confirmed witness for a recipe."""
    last_observed_diag: Optional[str] = None
    for source in sources:
        if source.language != recipe.language:
            continue
        applications = apply_recipe(
            source.corrected_src,
            recipe,
            max_candidates=max_candidates_per_source,
        )
        if not applications:
            continue
        is_clean = clean_cache.get(source.source_id)
        if is_clean is None:
            try:
                baseline = verifier.verify(
                    source.corrected_src,
                    list(source.compile_cmd),
                    logical_path=source.source_path,
                )
            except Exception:
                is_clean = False
            else:
                is_clean = baseline.ok
            clean_cache[source.source_id] = is_clean
        if not is_clean:
            continue

        for application in applications:
            try:
                verified = verifier.verify(
                    application.src,
                    list(source.compile_cmd),
                    logical_path=source.source_path,
                )
            except Exception:
                continue
            if verified.ok or verified.diag is None:
                continue
            last_observed_diag = verified.diag.diag_name
            if not _target_matches(
                target_name=target_name,
                target_id=target_id,
                observed_name=verified.diag.diag_name,
                observed_id=verified.diag.diag_id,
            ):
                continue
            snippet_end = max(
                application.end,
                application.start + len(application.replacement),
            )
            snippet = _snippet_around(
                application.src,
                application.start,
                snippet_end,
                radius=radius,
            )
            if snippet:
                return _TriggerWitness(source.source_id, snippet), last_observed_diag
    return None, last_observed_diag


def _witness_evidence(
    target_name: str,
    target_id: Optional[int],
    witness: _TriggerWitness,
) -> str:
    diagnostic = target_name
    if target_id is not None:
        diagnostic += f" (DiagID {target_id})"
    return (
        "Compiler-validated trigger witness (synthesis evidence only; not a "
        "dataset record): a bounded mutation of a clean real production "
        f"translation unit produced primary typed diagnostic {diagnostic}.\n"
        "Mutated local code window:\n"
        + witness.mutated_snippet
    )


def build_witness_synthesis_requests(
    recipes: Iterable[LearnedRecipe],
    clean_sources: Iterable[CleanSourceTU],
    catalog: Catalog,
    verifier: BaseVerifier,
    *,
    covered_diag_names: Iterable[str] = (),
    eligible_diag_names: Iterable[str] | None = None,
    diag_ids: Mapping[str, int] | None = None,
    max_targets: int,
    snippets_per_target: int = 2,
    snippet_radius: int = 240,
    witness_radius: int = 360,
    max_witness_candidates_per_source: int = 2,
) -> WitnessBuildResult:
    """Construct target requests backed by an exact compiler trigger witness.

    The result is deterministic for deterministic verifier behavior and source
    order.  Each selected target has two clean real-code snippets and one
    compiler-validated mutation witness.  The witness-producing recipe remains
    confined to the audit output and is never serialized in the request.
    """
    if max_targets < 0:
        raise ValueError("max_targets must be non-negative")
    if not 2 <= snippets_per_target <= 5:
        raise ValueError("snippets_per_target must be between 2 and 5")
    if snippet_radius <= 0 or witness_radius <= 0:
        raise ValueError("snippet radii must be positive")
    if max_witness_candidates_per_source <= 0:
        raise ValueError("max_witness_candidates_per_source must be positive")

    covered = set(covered_diag_names)
    eligible = None if eligible_diag_names is None else set(eligible_diag_names)
    ids = dict(diag_ids or {})
    grouped: dict[str, list[LearnedRecipe]] = defaultdict(list)
    for recipe in recipes:
        grouped[recipe.diag_name].append(recipe)
    sources = tuple(sorted(clean_sources, key=lambda item: item.source_id))
    ordered_names = sorted(
        grouped,
        key=lambda name: (-max(recipe.support for recipe in grouped[name]), name),
    )

    requests: list[SynthesisRequest] = []
    audits: list[WitnessBuildAudit] = []
    clean_cache: dict[str, bool] = {}
    for name in ordered_names:
        if eligible is not None and name not in eligible:
            audits.append(WitnessBuildAudit(name, "skipped_not_gap"))
            continue
        if name in covered:
            audits.append(WitnessBuildAudit(name, "skipped_covered"))
            continue
        entry = catalog.by_name.get(name)
        if entry is None or not entry.is_error:
            audits.append(WitnessBuildAudit(name, "skipped_not_catalog_error"))
            continue
        if len(requests) >= max_targets:
            audits.append(WitnessBuildAudit(name, "deferred_max_targets"))
            continue

        portable = sorted(
            (recipe for recipe in grouped[name] if recipe.portable),
            key=lambda recipe: (-recipe.support, recipe.recipe_id),
        )
        if not portable:
            audits.append(WitnessBuildAudit(name, "skipped_no_portable_recipe"))
            continue

        selected: Optional[tuple[
            LearnedRecipe, tuple[str, ...], tuple[str, ...], _TriggerWitness,
        ]] = None
        observed_diag: Optional[str] = None
        had_two_snippets = False
        for recipe in portable:
            snippets, source_ids = _find_real_snippets(
                recipe,
                sources,
                count=snippets_per_target,
                radius=snippet_radius,
            )
            if len(snippets) != snippets_per_target:
                continue
            had_two_snippets = True
            witness, observed = _find_compiler_witness(
                recipe,
                sources,
                verifier,
                target_name=name,
                target_id=ids.get(name),
                clean_cache=clean_cache,
                radius=witness_radius,
                max_candidates_per_source=max_witness_candidates_per_source,
            )
            if observed is not None:
                observed_diag = observed
            if witness is not None:
                selected = recipe, snippets, source_ids, witness
                break

        if selected is None:
            status = "skipped_no_compiler_validated_witness"
            if not had_two_snippets:
                status = "skipped_no_two_real_snippets"
            audits.append(WitnessBuildAudit(
                name,
                status,
                recipe_id=portable[0].recipe_id,
                observed_diag=observed_diag,
            ))
            continue

        recipe, snippets, source_ids, witness = selected
        target_id = ids.get(name)
        if target_id is not None and (
            isinstance(target_id, bool) or not isinstance(target_id, int)
            or target_id < 0
        ):
            raise ValueError(f"invalid diagnostic id for {name}")
        requests.append(SynthesisRequest(
            diag_name=name,
            diag_id=target_id,
            diag_message=entry.message,
            component=entry.component or "Unknown",
            language=recipe.language,
            correct_snippets=snippets,
            evidence=DiagnosticEvidence(
                tablegen_definition=_normalized_tablegen_definition(entry),
                emission_evidence=_witness_evidence(name, target_id, witness),
            ),
        ))
        audits.append(WitnessBuildAudit(
            name,
            "selected",
            recipe_id=recipe.recipe_id,
            source_ids=source_ids,
            witness_source_id=witness.source_id,
        ))

    return WitnessBuildResult(tuple(requests), tuple(audits))
