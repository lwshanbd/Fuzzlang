from __future__ import annotations

import hashlib
import json

from gen.fuzzlang_dsl.build_witness_routed_source_pool import routed_sources
from gen.fuzzlang_dsl.injector import FuzzLangInjector
from gen.realcorpus.clean_source_pool import CleanSourceTU


def _injector(target: str) -> FuzzLangInjector:
    return FuzzLangInjector(target_diag=target, target_diag_id=None, language="c++", operation="replace", old_patterns=("x",), new_text="y", left_context=(), right_context=(), portable=True, replacement_parts=(("literal", "y"),))


def test_routed_sources_uses_only_canonical_pool_rows(tmp_path):
    injectors, witnesses, pool = [tmp_path / name for name in ("i.jsonl", "w.jsonl", "p.jsonl")]
    injectors.write_text(_injector("err_a").to_json() + "\n")
    witnesses.write_text(json.dumps({"diag_name": "err_a", "source_id": "llvm:a.cpp", "corrected_src": "DO NOT USE"}) + "\n")
    src = CleanSourceTU("llvm:a.cpp", "llvm", "a.cpp", "c++", "int a;\n", ("__CLANG__", "-fsyntax-only", "__SRC__"), hashlib.sha256(b"int a;\n").hexdigest(), "llvmorg-22.1.8")
    pool.write_text(json.dumps(src.to_dict()) + "\n")
    assert routed_sources(injectors, witnesses, pool) == [src]


def test_routed_sources_can_select_a_stable_injector_shard(tmp_path):
    injectors, witnesses, pool = [
        tmp_path / name for name in ("i.jsonl", "w.jsonl", "p.jsonl")
    ]
    injectors.write_text(
        _injector("err_a").to_json() + "\n" + _injector("err_b").to_json() + "\n"
    )
    witnesses.write_text(
        json.dumps({"diag_name": "err_a", "source_id": "llvm:a.cpp"}) + "\n"
        + json.dumps({"diag_name": "err_b", "source_id": "llvm:b.cpp"}) + "\n"
    )
    source_a = CleanSourceTU("llvm:a.cpp", "llvm", "a.cpp", "c++", "int a;\n", ("__CLANG__", "-fsyntax-only", "__SRC__"), hashlib.sha256(b"int a;\n").hexdigest(), "llvmorg-22.1.8")
    source_b = CleanSourceTU("llvm:b.cpp", "llvm", "b.cpp", "c++", "int b;\n", ("__CLANG__", "-fsyntax-only", "__SRC__"), hashlib.sha256(b"int b;\n").hexdigest(), "llvmorg-22.1.8")
    pool.write_text(
        json.dumps(source_a.to_dict()) + "\n" + json.dumps(source_b.to_dict()) + "\n"
    )

    assert routed_sources(
        injectors, witnesses, pool, shard_count=2, shard_index=1,
    ) == [source_b]
