from __future__ import annotations

import hashlib

from gen.fuzzlang_dsl.witness_sources import prioritize_witness_sources
from gen.realcorpus.clean_source_pool import CleanSourceTU


def _source(name: str) -> CleanSourceTU:
    text = f"int {name}() {{ return 0; }}\n"
    return CleanSourceTU(
        source_id=f"llvm:lib/{name}.cpp",
        project="llvm",
        source_path=f"lib/{name}.cpp",
        language="c++",
        corrected_src=text,
        compile_cmd=("__CLANG__", "-x", "c++", "__SRC__"),
        source_sha256=hashlib.sha256(text.encode()).hexdigest(),
        baseline_compiler="llvmorg-22.1.8",
    )


def test_prioritizes_selected_witness_sources_once_and_preserves_remaining_order():
    result = prioritize_witness_sources(
        [_source("a"), _source("b"), _source("c")],
        [
            {"status": "selected", "witness_source_id": "llvm:lib/b.cpp"},
            {"status": "selected", "witness_source_id": "llvm:lib/a.cpp"},
            {"status": "selected", "witness_source_id": "llvm:lib/b.cpp"},
            {"status": "skipped_no_compiler_validated_witness"},
        ],
    )

    assert [source.source_id for source in result.sources] == [
        "llvm:lib/b.cpp", "llvm:lib/a.cpp", "llvm:lib/c.cpp",
    ]
    assert result.prioritized_source_ids == (
        "llvm:lib/b.cpp", "llvm:lib/a.cpp",
    )
    assert result.missing_witness_source_ids == ()
