"""Rank real fragments for a target diagnostic by feature overlap, so injection
is attempted on plausibly-inducible fragments first. When the target has no
structural feature (e.g. a purely syntactic diagnostic), order is preserved and
the first k are returned."""
from __future__ import annotations

from gen.realcorpus.corpus import Fragment
from gen.realcorpus.targets import Target


def rank_fragments(target: Target, fragments: list[Fragment], *,
                   k: int) -> list[Fragment]:
    if not target.features:
        return fragments[:k]
    scored = sorted(
        enumerate(fragments),
        key=lambda it: (-len(target.features & it[1].features), it[0]),
    )
    return [f for _, f in scored[:k]]
