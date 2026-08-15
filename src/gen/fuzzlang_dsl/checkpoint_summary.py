"""Summarize durable campaign checkpoints after an intentional early stop."""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping, Sequence


def summarize_checkpoint_campaign(
    injectors: Sequence[Mapping[str, Any]],
    rejections: Iterable[Mapping[str, Any]],
    records: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return replay-compatible Injector metrics from complete JSONL checkpoints.

    This intentionally counts only candidate outcomes that carry an Injector
    identity.  It is for an early-stopped campaign, not a substitute for a
    completed campaign manifest.
    """
    targets: dict[str, str] = {}
    for injector in injectors:
        injector_id = injector.get("injector_id")
        target = injector.get("target")
        if not isinstance(injector_id, str) or not injector_id:
            raise ValueError("each Injector requires a non-empty injector_id")
        if not isinstance(target, Mapping) or not isinstance(target.get("diag_name"), str):
            raise ValueError(f"Injector {injector_id} requires target.diag_name")
        targets[injector_id] = target["diag_name"]

    compiled: Counter[str] = Counter()
    for rejection in rejections:
        injector_id = rejection.get("injector_id")
        if injector_id in targets:
            compiled[injector_id] += 1

    exact: Counter[str] = Counter()
    for record in records:
        provenance = record.get("provenance")
        detail = provenance.get("detail") if isinstance(provenance, Mapping) else None
        injector_id = detail.get("injector_id") if isinstance(detail, Mapping) else None
        if injector_id in targets:
            exact[injector_id] += 1

    return [
        {
            "injector_id": injector_id,
            "target_diag": target,
            "compiled": compiled[injector_id] + exact[injector_id],
            "exact_target": exact[injector_id],
            "records_emitted": exact[injector_id],
        }
        for injector_id, target in targets.items()
        if compiled[injector_id] or exact[injector_id]
    ]
