"""Delete a single statement-terminating ``;`` — the canonical missing-semicolon
error. One mutant per code semicolon (literals/comments excluded)."""
from __future__ import annotations

from gen.mutate.base import BaseMutation, Mutant
from gen.mutate._scan import iter_code_chars


class DeleteSemicolon(BaseMutation):
    name = "delete_semicolon"

    def mutate(self, src: str) -> list[Mutant]:
        mutants = []
        for i, c in iter_code_chars(src):
            if c == ";":
                mutants.append(Mutant(
                    src=src[:i] + src[i + 1:],
                    description=f"delete ';' at offset {i}",
                    expected_diag="expected_semi",
                ))
        return mutants
