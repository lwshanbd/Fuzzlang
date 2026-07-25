"""Exact seed replay for Gemma-authored FuzzLang DSL Injectors.

The direct synthesis prompt gives Gemma diagnostic evidence and real source
windows.  Schema acceptance alone is deliberately insufficient: an emitted
Injector must reproduce its declared typed diagnostic on at least one of those
same clean production translation units before it can be replayed elsewhere.
"""
from __future__ import annotations

import hashlib
from typing import Protocol

from foundation.record import Origin, Provenance, Record, Split
from gen.fuzzlang_dsl.code_witness import CodeWitnessRequest
from gen.fuzzlang_dsl.injector import FuzzLangInjector, apply_injector


class TypedVerifier(Protocol):
    def verify(self, source: str, compile_cmd: list[str], *, logical_path: str):
        """Compile one candidate and return its primary typed diagnostic."""


def replay_direct_injector_on_source(
    injector: FuzzLangInjector,
    request: CodeWitnessRequest,
    verifier: TypedVerifier,
) -> Record | None:
    """Return one paired record only when direct Injector replay is exact.

    This is the admission bridge for the direct-DSL path.  It does not trust
    the model's target fields: both name and numeric ID must agree with the
    compiler result.  The unmodified production source remains the paired
    ``corrected_src``.
    """
    if (
        injector.target_diag != request.diag_name
        or injector.language != request.language
        or injector.target_diag_id != request.diag_id
    ):
        return None
    for application in apply_injector(
        request.corrected_src, injector, max_candidates=1,
    ):
        verified = verifier.verify(
            application.src, list(request.compile_cmd),
            logical_path=request.source_path,
        )
        diag = verified.diag
        if (
            verified.ok or diag is None
            or diag.diag_name != request.diag_name
            or diag.diag_id != request.diag_id
        ):
            continue
        record_id = "direct-source-injector-" + hashlib.sha256(
            (request.source_id + "\0" + injector.injector_id + "\0" + application.src).encode()
        ).hexdigest()[:24]
        return Record(
            record_id=record_id,
            erroneous_src=application.src,
            corrected_src=request.corrected_src,
            diagnostics=(diag,),
            split=Split.TRAIN,
            language=request.language,
            provenance=Provenance(
                origin=Origin.LLM,
                source=request.source_id,
                detail={
                    "strategy": "gemma_direct_fuzzlang_injector",
                    "project": request.project,
                    "source_path": request.source_path,
                    "compile_cmd": list(request.compile_cmd),
                    "injector_id": injector.injector_id,
                    "injector_replay_exact": True,
                    "target_diag": request.diag_name,
                },
            ),
        )
    return None
