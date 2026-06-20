"""Delete a single ``,`` token (declarator lists, call args, init lists...).

A representative "delete a punctuation token" mutation. One mutant per code
comma (literals/comments excluded).
"""
from __future__ import annotations

from gen.mutate.base import BaseMutation, Mutant
from gen.mutate._scan import iter_code_chars


class DeleteComma(BaseMutation):
    name = "delete_comma"

    def mutate(self, src: str) -> list[Mutant]:
        mutants = []
        for i, c in iter_code_chars(src):
            if c == ",":
                mutants.append(Mutant(
                    src=src[:i] + src[i + 1:],
                    description=f"delete ',' at offset {i}",
                    expected_diag=None,
                ))
        return mutants
