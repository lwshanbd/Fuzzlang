"""Mechanical mutation library: introduce errors into correct C/C++ source.

Mutations are *pure source transforms* — they do not compile. Each concrete
mutation turns one correct source into zero-or-more :class:`Mutant` candidates;
the verifier (in :mod:`gen.collect`) decides which candidates actually trigger a
real compiler diagnostic and become dataset records.

Text/token-level mutations need no libclang and are always available. AST-based
mutations (asterisk, lambda) require ``clang.cindex`` and are registered only
when it imports — see :func:`_register_ast_mutations`.
"""
from __future__ import annotations

from gen.mutate.base import BaseMutation, Mutant
from gen.mutate.registry import all_mutations, get, register, text_mutations

# --- text/token-level mutations: always available ---------------------------
from gen.mutate.delete_semicolon import DeleteSemicolon
from gen.mutate.delete_bracket import DeleteBracket
from gen.mutate.replace_colon_semicolon import ReplaceColonWithSemicolon
from gen.mutate.delete_comma import DeleteComma

for _m in (DeleteSemicolon(), DeleteBracket(),
           ReplaceColonWithSemicolon(), DeleteComma()):
    register(_m)


def _register_ast_mutations() -> bool:
    """Register libclang-backed mutations if ``clang.cindex`` is importable.

    Returns True if AST mutations were registered. Text mutations remain the
    fallback when libclang is absent (as on dev machines without it).
    """
    try:
        import clang.cindex  # noqa: F401
    except Exception:
        return False
    # AST-based mutations (asterisk, lambda) plug in here once ported.
    return True


_register_ast_mutations()

__all__ = [
    "BaseMutation",
    "Mutant",
    "all_mutations",
    "text_mutations",
    "get",
    "register",
    "DeleteSemicolon",
    "DeleteBracket",
    "ReplaceColonWithSemicolon",
    "DeleteComma",
]
