"""Replace a single ``:`` with ``;`` (ternary, labels, base lists, bitfields...).

Colons that are part of ``::`` (scope resolution) are skipped — mangling those
is a different, noisier mutation.
"""
from __future__ import annotations

from gen.mutate.base import BaseMutation, Mutant
from gen.mutate._scan import iter_code_chars


class ReplaceColonWithSemicolon(BaseMutation):
    name = "replace_colon_with_semicolon"

    def mutate(self, src: str) -> list[Mutant]:
        code = [(i, c) for i, c in iter_code_chars(src)]
        colon_offsets = {i for i, c in code if c == ":"}
        mutants = []
        for i in sorted(colon_offsets):
            # Skip '::' (either side adjacent to another colon).
            if (i - 1) in colon_offsets or (i + 1) in colon_offsets:
                continue
            mutants.append(Mutant(
                src=src[:i] + ";" + src[i + 1:],
                description=f"replace ':' with ';' at offset {i}",
                expected_diag="expected_semi",
            ))
        return mutants
