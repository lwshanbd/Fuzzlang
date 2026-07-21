from __future__ import annotations

import hashlib
import json
import sys

from foundation.diagnostics.catalog import Catalog, DiagEntry
from gen.fuzzlang_dsl import run_build_requests
from gen.realcorpus.clean_source_pool import CleanSourceTU
from gen.realcorpus.recipes import LearnedRecipe


def _source() -> CleanSourceTU:
    text = "bool f() { return true; }\n"
    return CleanSourceTU(
        source_id="llvm:lib/a.cpp",
        project="llvm",
        source_path="lib/a.cpp",
        language="c++",
        corrected_src=text,
        compile_cmd=("__CLANG__", "-x", "c++", "__SRC__"),
        source_sha256=hashlib.sha256(text.encode()).hexdigest(),
        baseline_compiler="llvmorg-22.1.8",
    )


def _recipe() -> LearnedRecipe:
    return LearnedRecipe(
        recipe_id="r1",
        diag_name="err_gap",
        language="c++",
        operation="replace",
        old_patterns=("true",),
        new_text="false",
        left_context=("return",),
        right_context=(";",),
        portable=True,
        replacement_parts=(("literal", "false"),),
    )


def test_cli_writes_model_requests_and_retrieval_audit_without_recipe_edit_leakage(
    tmp_path, monkeypatch,
):
    recipes = tmp_path / "recipes.jsonl"
    recipes.write_text(json.dumps(_recipe().to_dict()) + "\n")
    sources = tmp_path / "sources.jsonl"
    # Two source identities are needed even when their real syntax shape is the
    # same; duplicate the content with a distinct production-relative path.
    second = CleanSourceTU(
        **{**_source().__dict__, "source_id": "llvm:lib/b.cpp", "source_path": "lib/b.cpp"}
    )
    sources.write_text(
        json.dumps(_source().to_dict()) + "\n" + json.dumps(second.to_dict()) + "\n"
    )
    out = tmp_path / "requests.jsonl"
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(
        run_build_requests,
        "load_catalog",
        lambda: Catalog([DiagEntry("err_gap", "Error", "gap message", "Sema")]),
    )
    monkeypatch.setattr(
        run_build_requests,
        "resolve_diag_ids",
        lambda _names, _bin: {"err_gap": 17},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_build_requests.py",
            "--recipes", str(recipes),
            "--clean-sources", str(sources),
            "--diagtool-bin", "/fake/diagtool",
            "--out", str(out),
            "--audit-out", str(audit),
            "--max-targets", "1",
        ],
    )

    assert run_build_requests.main() == 0
    request = json.loads(out.read_text())
    assert request["diag_id"] == 17
    assert request["diag_name"] == "err_gap"
    assert "r1" not in out.read_text()
    assert json.loads(audit.read_text())["retrieval_recipe_id"] == "r1"
