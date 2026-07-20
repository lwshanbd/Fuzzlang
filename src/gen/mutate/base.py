"""Abstract mutation interface and the Mutant value type.

A mutation is a pure source transform: given correct source it returns a list of
candidate broken sources. It never compiles anything — verification is a
separate stage (:mod:`gen.collect`).
"""
from __future__ import annotations

import hashlib
import heapq
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class Mutant:
    """One candidate produced by a mutation.

    Attributes:
        src: the mutated (intended-to-be-broken) source.
        description: short human-readable summary, e.g. ``delete ';' at offset 9``.
        expected_diag: optional hint at the diagnostic this should trigger — a
            diag name (``err_expected_semi_declaration``) or a looser family
            token (``expected_semi``). Purely advisory; the verifier reports the
            ground truth.
    """

    src: str
    description: str
    expected_diag: Optional[str] = None


class BaseMutation(ABC):
    """A named source-to-mutants transform.

    Subclasses set :attr:`name` and implement :meth:`mutate`. ``requires_libclang``
    lets the registry separate always-available text transforms from AST-based
    ones that need ``clang.cindex``.
    """

    name: str = ""
    requires_libclang: bool = False

    @abstractmethod
    def mutate(self, src: str) -> list[Mutant]:
        """Return zero or more mutant candidates for `src`. Pure; no compilation."""

    def iter_mutants(self, src: str) -> Iterable[Mutant]:
        """Yield candidates lazily; subclasses may override to avoid a full list."""
        yield from self.mutate(src)

    def bounded_mutants(
        self, src: str, *, max_candidates: int, seed: int,
    ) -> list[Mutant]:
        """Select a deterministic bottom-k sample without retaining every mutant.

        Selection hashes stable mutation metadata rather than depending on Python's
        randomized hash or traversal-side random state.  At most ``max_candidates``
        complete source copies are retained while the iterator is consumed.
        """
        if max_candidates <= 0:
            return []
        source_hash = hashlib.sha256(src.encode("utf-8")).hexdigest()
        selected: list[tuple[int, int, Mutant]] = []
        for ordinal, mutant in enumerate(self.iter_mutants(src)):
            payload = (
                f"{seed}|{self.name}|{source_hash}|{ordinal}|"
                f"{mutant.description}|{mutant.expected_diag or ''}"
            ).encode("utf-8")
            score = int.from_bytes(hashlib.sha256(payload).digest(), "big")
            entry = (-score, -ordinal, mutant)
            if len(selected) < max_candidates:
                heapq.heappush(selected, entry)
            elif entry > selected[0]:
                heapq.heapreplace(selected, entry)
        return [
            mutant for _negative_score, _negative_ordinal, mutant in sorted(
                selected, key=lambda item: (-item[0], -item[1])
            )
        ]
