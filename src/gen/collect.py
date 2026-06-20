"""Run mutations through a verifier and emit dataset Records.

This is where the **correct-code invariant** lands: a mutant becomes a Record
only if the *original* source compiles cleanly (so it is genuinely correct) and
the mutated source triggers a real error diagnostic. Every emitted record's
``corrected_src`` is that original correct source — errors are introduced into
correct code, never the other way round.

Mutation (pure transform) and verification (compile) stay separate: mutations
come from :mod:`gen.mutate`, compilation from a :class:`foundation.verifier`
backend (``FuzzlangClangVerifier`` in production, ``MockVerifier`` in tests).
"""
from __future__ import annotations

import hashlib
from typing import Optional, Sequence

from foundation.record import Origin, Provenance, Record, Split
from foundation.verifier.base import PLACEHOLDER, BaseVerifier
from gen.mutate import text_mutations
from gen.mutate.base import BaseMutation

# Syntax-only is enough: we only need the front-end diagnostic, not codegen.
_CMD_CXX = ["__CLANG__", "-fsyntax-only", "-std=c++17", "-x", "c++", PLACEHOLDER]
_CMD_C = ["__CLANG__", "-fsyntax-only", "-x", "c", PLACEHOLDER]


def default_compile_cmd(language: str) -> list[str]:
    return list(_CMD_C if language.lower() == "c" else _CMD_CXX)


def _record_id(source: str, mutation: str, description: str, src: str) -> str:
    h = hashlib.sha256(f"{source}|{mutation}|{description}|{src}".encode()).hexdigest()
    return f"{mutation}-{h[:12]}"


def collect_records(
    correct_src: str,
    verifier: BaseVerifier,
    *,
    source: str,
    mutations: Optional[Sequence[BaseMutation]] = None,
    language: str = "c++",
    split: Split = Split.TRAIN,
    compile_cmd: Optional[list[str]] = None,
    logical_path: Optional[str] = None,
) -> list[Record]:
    """Mutate `correct_src`, verify each mutant, and return the records that pass.

    Args:
        correct_src: a source believed to compile cleanly.
        verifier: compile backend.
        source: provenance source name (e.g. ``llvm:clang/lib/Sema/Foo.cpp``).
        mutations: which mutations to run; defaults to all text mutations.
        language: ``c++`` (default) or ``c`` — selects the default compile cmd.
        split: target split for the records (TRAIN by default).
        compile_cmd: override the default compile command (uses ``__CLANG__`` /
            ``__SRC__`` placeholder tokens).
        logical_path: stable path put into ``DiagInfo.file``; defaults to `source`.

    Returns:
        Records (one per kept mutant). Empty if the original does not compile.
    """
    if mutations is None:
        mutations = text_mutations()
    cmd = compile_cmd if compile_cmd is not None else default_compile_cmd(language)
    lpath = logical_path if logical_path is not None else source

    # Correct-code invariant: the original must compile cleanly, else no pairs.
    base = verifier.verify(correct_src, cmd, logical_path=lpath)
    if not base.ok:
        return []

    records: list[Record] = []
    for mutation in mutations:
        for mutant in mutation.mutate(correct_src):
            result = verifier.verify(mutant.src, cmd, logical_path=lpath)
            if result.ok or result.diag is None:
                continue  # didn't break, or no usable error diagnostic
            records.append(Record(
                record_id=_record_id(source, mutation.name,
                                      mutant.description, mutant.src),
                erroneous_src=mutant.src,
                corrected_src=correct_src,
                diagnostics=(result.diag,),
                provenance=Provenance(
                    origin=Origin.MUTATE,
                    source=source,
                    detail={
                        "mutation": mutation.name,
                        "description": mutant.description,
                        "expected_diag": mutant.expected_diag,
                    },
                ),
                split=split,
                language=language,
            ))
    return records
