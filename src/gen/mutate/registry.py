"""Registry of available mutations, addressable by name.

Concrete mutations register an instance here (done from the package ``__init__``
so importing :mod:`gen.mutate` is enough). Text transforms are always present;
AST-based transforms register only when ``clang.cindex`` is importable.
"""
from __future__ import annotations

from gen.mutate.base import BaseMutation

_REGISTRY: dict[str, BaseMutation] = {}


def register(mutation: BaseMutation) -> BaseMutation:
    """Register a mutation instance by its ``name``. Last registration wins."""
    if not mutation.name:
        raise ValueError(f"{type(mutation).__name__} has no name")
    _REGISTRY[mutation.name] = mutation
    return mutation


def get(name: str) -> BaseMutation:
    """Return the mutation registered under `name`; raise KeyError if absent."""
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"no mutation named {name!r}; available: {sorted(_REGISTRY)}"
        ) from None


def all_mutations() -> list[BaseMutation]:
    """All registered mutations, sorted by name for determinism."""
    return [_REGISTRY[k] for k in sorted(_REGISTRY)]


def text_mutations() -> list[BaseMutation]:
    """Registered mutations that need no libclang (always runnable)."""
    return [m for m in all_mutations() if not m.requires_libclang]
