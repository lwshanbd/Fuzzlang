"""Delete one half of a matched bracket pair, unbalancing the source.

Pairs ``()``, ``[]`` and ``{}`` are matched with a per-kind stack over the code
characters (literals/comments excluded). For each matched pair we emit two
mutants: one dropping the opener, one dropping the closer. Unmatched delimiters
produce nothing.
"""
from __future__ import annotations

from typing import Iterable

from gen.mutate.base import BaseMutation, Mutant
from gen.mutate._scan import iter_code_chars

_PAIRS = {")": "(", "]": "[", "}": "{"}
_OPENERS = set(_PAIRS.values())


class DeleteBracket(BaseMutation):
    name = "delete_bracket"

    def mutate(self, src: str) -> list[Mutant]:
        return list(self.iter_mutants(src))

    def iter_mutants(self, src: str) -> Iterable[Mutant]:
        # Match pairs: a stack per opener kind holding open-char offsets.
        stacks: dict[str, list[int]] = {o: [] for o in _OPENERS}
        pairs: list[tuple[int, int]] = []  # (open_offset, close_offset)
        for i, c in iter_code_chars(src):
            if c in _OPENERS:
                stacks[c].append(i)
            elif c in _PAIRS:
                opener = _PAIRS[c]
                if stacks[opener]:
                    o = stacks[opener].pop()
                    pairs.append((o, i))
        pairs.sort()

        for o, close in pairs:
            yield Mutant(
                src=src[:o] + src[o + 1:],
                description=f"delete '{src[o]}' at offset {o}",
                expected_diag="expected_bracket",
            )
            yield Mutant(
                src=src[:close] + src[close + 1:],
                description=f"delete '{src[close]}' at offset {close}",
                expected_diag="expected_bracket",
            )
