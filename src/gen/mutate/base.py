"""Abstract mutation interface and the Mutant value type.

A mutation is a pure source transform: given correct source it returns a list of
candidate broken sources. It never compiles anything — verification is a
separate stage (:mod:`gen.collect`).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


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
