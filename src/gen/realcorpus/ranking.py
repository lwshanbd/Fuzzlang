"""Rank real fragments for a target diagnostic by feature overlap, so injection
is attempted on plausibly-inducible fragments first. When the target has no
structural feature (e.g. a purely syntactic diagnostic), order is preserved and
the first k are returned."""
from __future__ import annotations

import hashlib

from gen.realcorpus.corpus import Fragment
from gen.realcorpus.targets import Target


def rank_fragments(target: Target, fragments: list[Fragment], *,
                   k: int) -> list[Fragment]:
    """Fragments to attempt for a target. When the target has feature tags, GATE
    to fragments sharing at least one feature (applicability), ranked by overlap;
    an empty result means the target is skipped this pass. When the target has no
    tags, fall back to the first k (no applicability signal)."""
    def tie_break(f: Fragment) -> str:
        payload = f"{target.name}|{f.rel_path}|{f.span[0]}|{f.region_type}"
        return hashlib.sha256(payload.encode()).hexdigest()

    if target.features:
        candidates = [f for f in fragments if target.features & f.features]
    else:
        candidates = list(fragments)
    candidates.sort(key=lambda f: (
        -len(target.features & f.features), tie_break(f)))

    # A target should see different real files before a second region from the
    # same TU.  This removes the severe early-file bias of stable top-k ranking.
    first_per_tu: list[Fragment] = []
    repeats: list[Fragment] = []
    seen: set[str] = set()
    for frag in candidates:
        if frag.rel_path in seen:
            repeats.append(frag)
        else:
            seen.add(frag.rel_path)
            first_per_tu.append(frag)
    return (first_per_tu + repeats)[:k]
