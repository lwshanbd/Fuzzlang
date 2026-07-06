"""Rank real fragments for a target diagnostic by feature overlap, so injection
is attempted on plausibly-inducible fragments first. When the target has no
structural feature (e.g. a purely syntactic diagnostic), order is preserved and
the first k are returned."""
from __future__ import annotations

from gen.realcorpus.corpus import Fragment
from gen.realcorpus.targets import Target


def rank_fragments(target: Target, fragments: list[Fragment], *,
                   k: int) -> list[Fragment]:
    """Fragments to attempt for a target. When the target has feature tags, GATE
    to fragments sharing at least one feature (applicability), ranked by overlap;
    an empty result means the target is skipped this pass. When the target has no
    tags, fall back to the first k (no applicability signal)."""
    if not target.features:
        return fragments[:k]
    matching = [(i, f) for i, f in enumerate(fragments)
                if target.features & f.features]
    matching.sort(key=lambda it: (-len(target.features & it[1].features), it[0]))
    return [f for _, f in matching[:k]]
