"""Recover bounded Injectors from exact witnesses that replaced comments."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from typing import Iterable

from foundation.record import Origin, Provenance, Record
from foundation.verifier.base import BaseVerifier
from gen.fuzzlang_dsl.context_variants import extract_contextual_injectors
from gen.fuzzlang_dsl.injector import FuzzLangInjector, apply_injector
from gen.mutate._scan import code_mask
from gen.realcorpus.recipes import minimal_edit


@dataclass(frozen=True)
class RecoveredInjection:
    """One independently recompiled pair and its portable Injectors."""

    record: Record
    injectors: tuple[FuzzLangInjector, ...]


def _contains_only_comment_or_whitespace(text: str) -> bool:
    mask = code_mask(text)
    return bool(text) and not any(
        keep and not char.isspace()
        for char, keep in zip(text, mask)
    )


def _target_matches(record: Record, observed) -> bool:
    target = record.primary_diagnostic
    return (
        target is not None
        and observed is not None
        and observed.diag_name == target.diag_name
        and (
            target.diag_id is None
            or observed.diag_id == target.diag_id
        )
    )


def recover_comment_replacement(
    record: Record,
    verifier: BaseVerifier,
    *,
    context_tokens: Iterable[int] = (1, 2, 3),
    max_candidates_per_injector: int = 4,
) -> RecoveredInjection | None:
    """Normalize a comment replacement to an insertion and verify it afresh.

    Models occasionally replace a nearby documentation comment with trigger
    code.  Comments are intentionally invisible to the lexical DSL, so that
    exact edit is not portable.  This recovery keeps the original comment,
    distils the added code as a bounded insertion, applies that Injector back
    to the clean source, and accepts only an exact typed-diagnostic match.
    """

    if (
        record.corrected_src is None
        or record.primary_diagnostic is None
        or max_candidates_per_injector <= 0
    ):
        return None
    detail = record.provenance.detail
    compile_cmd = detail.get("compile_cmd")
    source_path = detail.get("source_path")
    if (
        not isinstance(compile_cmd, list)
        or any(not isinstance(arg, str) for arg in compile_cmd)
        or not isinstance(source_path, str)
        or not source_path
    ):
        return None

    baseline = verifier.verify(
        record.corrected_src,
        compile_cmd,
        logical_path=source_path,
    )
    if not baseline.ok:
        return None

    start, old_text, new_text = minimal_edit(
        record.corrected_src,
        record.erroneous_src,
    )
    if (
        not _contains_only_comment_or_whitespace(old_text)
        or not new_text.strip()
    ):
        return None
    separator = "" if new_text.endswith("\n") else "\n"
    provisional_source = (
        record.corrected_src[:start]
        + new_text
        + separator
        + record.corrected_src[start:]
    )
    provisional = replace(record, erroneous_src=provisional_source)
    provisional_injectors = extract_contextual_injectors(
        provisional,
        diag_id=record.primary_diagnostic.diag_id,
        context_tokens=context_tokens,
    )

    for injector in provisional_injectors:
        for application in apply_injector(
            record.corrected_src,
            injector,
            max_candidates=max_candidates_per_injector,
        ):
            verified = verifier.verify(
                application.src,
                compile_cmd,
                logical_path=source_path,
            )
            if verified.ok or not _target_matches(record, verified.diag):
                continue
            record_id = "recovered-witness-" + hashlib.sha256(
                (
                    record.provenance.source
                    + "\0"
                    + application.src
                ).encode()
            ).hexdigest()[:24]
            recovered_record = Record(
                record_id=record_id,
                erroneous_src=application.src,
                corrected_src=record.corrected_src,
                diagnostics=(verified.diag,),
                provenance=Provenance(
                    Origin.MUTATE,
                    record.provenance.source,
                    detail={
                        **detail,
                        "strategy": "comment_replacement_insertion_recovery",
                        "source_record_id": record.record_id,
                        "primary_matches_target": True,
                    },
                ),
                split=record.split,
                language=record.language,
            )
            final_injectors = extract_contextual_injectors(
                recovered_record,
                diag_id=verified.diag.diag_id,
                context_tokens=context_tokens,
            )
            if not final_injectors:
                continue
            return RecoveredInjection(
                recovered_record,
                final_injectors,
            )
    return None

