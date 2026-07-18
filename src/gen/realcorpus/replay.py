"""Replay learned diagnostic recipes on unseen, clean real-project sources."""
from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Iterable, Optional

from foundation.record import Origin, Provenance, Record, Split
from foundation.verifier.base import BaseVerifier
from gen.realcorpus.collect import count_errors
from gen.realcorpus.corpus import is_test_path
from gen.realcorpus.finalize import portable_source_path
from gen.realcorpus.recipes import (
    LearnedRecipe,
    apply_recipe,
    build_token_index,
    lex_tokens,
)


@dataclass(frozen=True)
class ReplayOutcome:
    status: str
    records: tuple[Record, ...] = ()
    candidates_verified: int = 0


@dataclass(frozen=True)
class ReplayRevalidation:
    status: str
    record: Optional[Record] = None


def revalidate_replay_record(
    record: Record, verifier: BaseVerifier,
) -> ReplayRevalidation:
    """Re-run the paired compile gate for one learned-replay Record."""
    if record.corrected_src is None:
        return ReplayRevalidation("missing_corrected_src")
    detail = record.provenance.detail
    source_path = detail.get("source_path")
    compile_cmd = detail.get("compile_cmd")
    if not source_path or is_test_path(source_path):
        return ReplayRevalidation("test_or_missing_source")
    if not isinstance(compile_cmd, list) or "__SRC__" not in compile_cmd:
        return ReplayRevalidation("invalid_compile_cmd")

    corrected = verifier.verify(
        record.corrected_src, compile_cmd, logical_path=source_path
    )
    if not corrected.ok:
        return ReplayRevalidation("corrected_not_clean")
    erroneous = verifier.verify(
        record.erroneous_src, compile_cmd, logical_path=source_path
    )
    if erroneous.ok:
        return ReplayRevalidation("buggy_became_clean")
    if erroneous.diag is None or not erroneous.diag.diag_name:
        return ReplayRevalidation("missing_primary_diagnostic")
    expected = record.primary_diagnostic.diag_name if record.primary_diagnostic else None
    if expected != erroneous.diag.diag_name:
        return ReplayRevalidation("diagnostic_drift")

    diag = replace(erroneous.diag, file=source_path)
    target_match = diag.diag_name == detail.get("target_diag")
    updated_detail = {
        **detail,
        "primary_matches_target": target_match,
        "generation_label": "exact_target" if target_match else "near_miss",
        "cascade_size": max(1, count_errors(erroneous.raw_stderr)),
        "revalidated": True,
    }
    updated = replace(
        record,
        diagnostics=(diag,),
        provenance=replace(record.provenance, detail=updated_detail),
    )
    return ReplayRevalidation("accepted", updated)


def round_robin_recipes(
    recipes: Iterable[LearnedRecipe],
) -> list[LearnedRecipe]:
    """Schedule one strong portable recipe per diagnostic before deeper variants."""
    by_diag: dict[str, list[LearnedRecipe]] = defaultdict(list)
    for recipe in recipes:
        if recipe.portable:
            by_diag[recipe.diag_name].append(recipe)
    for bucket in by_diag.values():
        bucket.sort(key=lambda recipe: (-recipe.support, recipe.recipe_id))
    diag_order = sorted(
        by_diag,
        key=lambda diag: (-by_diag[diag][0].support, diag),
    )
    scheduled: list[LearnedRecipe] = []
    depth = 0
    while any(depth < len(by_diag[diag]) for diag in diag_order):
        for diag in diag_order:
            if depth < len(by_diag[diag]):
                scheduled.append(by_diag[diag][depth])
        depth += 1
    return scheduled


def source_diverse_recipes(
    recipes: Iterable[LearnedRecipe], source_salt: str,
) -> list[LearnedRecipe]:
    """Round-robin recipes with a deterministic per-source diagnostic order."""
    by_diag: dict[str, list[LearnedRecipe]] = defaultdict(list)
    for recipe in recipes:
        if recipe.portable:
            by_diag[recipe.diag_name].append(recipe)
    for bucket in by_diag.values():
        bucket.sort(key=lambda recipe: (-recipe.support, recipe.recipe_id))
    diag_order = sorted(
        by_diag,
        key=lambda diag: hashlib.sha256(
            f"{source_salt}|{diag}".encode()
        ).hexdigest(),
    )
    scheduled: list[LearnedRecipe] = []
    depth = 0
    while any(depth < len(by_diag[diag]) for diag in diag_order):
        scheduled.extend(
            by_diag[diag][depth] for diag in diag_order
            if depth < len(by_diag[diag])
        )
        depth += 1
    return scheduled


def _record_id(project: str, path: str, recipe_id: str, mutant: str) -> str:
    payload = f"{project}|{path}|{recipe_id}|{mutant}".encode()
    return "recipe-replay-" + hashlib.sha256(payload).hexdigest()[:12]


def replay_source(
    source: str,
    *,
    path: str,
    compile_cmd: list[str],
    language: str,
    recipes: Iterable[Optional[LearnedRecipe]],
    verifier: BaseVerifier,
    project: str,
    excluded_sources: set[str] | frozenset[str] = frozenset(),
    max_records: int = 5,
    max_candidates_per_recipe: int = 2,
    max_verifications: int = 50,
    exact_only: bool = False,
) -> ReplayOutcome:
    """Verify a clean TU, replay compatible recipes, and emit canonical Records."""
    logical_path = portable_source_path(path)
    source_key = f"{project}:{logical_path}"
    if is_test_path(path):
        return ReplayOutcome("test_source")
    if source_key in excluded_sources:
        return ReplayOutcome("excluded_source")
    if max_records <= 0:
        return ReplayOutcome("record_cap_zero")

    baseline = verifier.verify(source, compile_cmd, logical_path=logical_path)
    if not baseline.ok:
        return ReplayOutcome("corrected_not_clean")

    records: list[Record] = []
    actual_diags: set[str] = set()
    candidates_verified = 0
    tokens = lex_tokens(source)
    token_index = build_token_index(tokens)
    for recipe in recipes:
        if recipe is None or not recipe.portable or recipe.language != language:
            continue
        applications = apply_recipe(
            source, recipe, max_candidates=max_candidates_per_recipe,
            tokens=tokens, token_index=token_index,
        )
        for application in applications:
            if candidates_verified >= max_verifications:
                return ReplayOutcome(
                    "accepted" if records else "verification_cap",
                    tuple(records), candidates_verified,
                )
            result = verifier.verify(
                application.src, compile_cmd, logical_path=logical_path
            )
            candidates_verified += 1
            if result.ok or result.diag is None or not result.diag.diag_name:
                continue
            diag = replace(result.diag, file=logical_path)
            target_match = diag.diag_name == recipe.diag_name
            if exact_only and not target_match:
                continue
            # One instance per actual diagnostic per TU prevents a generic
            # recipe from flooding the dataset with equivalent failures.
            if diag.diag_name in actual_diags:
                continue
            actual_diags.add(diag.diag_name)
            cascade_size = max(1, count_errors(result.raw_stderr))
            record = Record(
                record_id=_record_id(
                    project, logical_path, recipe.recipe_id, application.src
                ),
                erroneous_src=application.src,
                corrected_src=source,
                diagnostics=(diag,),
                provenance=Provenance(
                    origin=Origin.MUTATE,
                    source=source_key,
                    detail={
                        "strategy": "learned_recipe_replay",
                        "recipe_id": recipe.recipe_id,
                        "recipe_support": recipe.support,
                        "recipe_operation": recipe.operation,
                        "recipe_exemplars": list(recipe.exemplar_ids[:5]),
                        "target_diag": recipe.diag_name,
                        "primary_matches_target": target_match,
                        "generation_label": (
                            "exact_target" if target_match else "near_miss"
                        ),
                        "cascade_size": cascade_size,
                        "compile_cmd": compile_cmd,
                        "source_path": logical_path,
                        "edit": {
                            "start": application.start,
                            "end": application.end,
                            "replacement": application.replacement,
                        },
                    },
                ),
                split=Split.EVAL,
                language=language,
            )
            records.append(record)
            if len(records) >= max_records:
                return ReplayOutcome(
                    "accepted", tuple(records), candidates_verified
                )

    return ReplayOutcome(
        "accepted" if records else "no_verified_mutants",
        tuple(records),
        candidates_verified,
    )
