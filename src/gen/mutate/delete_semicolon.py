"""Delete a single statement-terminating ``;`` — the canonical missing-semicolon
error. One mutant per code semicolon (literals/comments excluded)."""
from __future__ import annotations

from typing import Iterable

from gen.mutate.base import BaseMutation, Mutant
from gen.mutate._scan import iter_code_chars


class DeleteSemicolon(BaseMutation):
    name = "delete_semicolon"

    def mutate(self, src: str) -> list[Mutant]:
        return list(self.iter_mutants(src))

    def iter_mutants(self, src: str) -> Iterable[Mutant]:
        for i, c in iter_code_chars(src):
            if c == ";":
                yield Mutant(
                    src=src[:i] + src[i + 1:],
                    description=f"delete ';' at offset {i}",
                    expected_diag="expected_semi",
                )
