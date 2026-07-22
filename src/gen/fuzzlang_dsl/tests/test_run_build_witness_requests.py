from __future__ import annotations

import hashlib
import json
import sys

from foundation.diagnostics.catalog import Catalog, DiagEntry
from foundation.types import DiagInfo, VerifierResult
from foundation.verifier.mock import MockVerifier
from gen.fuzzlang_dsl import run_build_witness_requests
from gen.realcorpus.clean_source_pool import CleanSourceTU
from gen.realcorpus.recipes import LearnedRecipe


def _source(path: str) -> CleanSourceTU:
    text = "bool f() { return true; }\n"
    return CleanSourceTU(
        source_id=f"llvm:{path}",
        project="llvm",
        source_path=path,
        language="c++",
        corrected_src=text,
        compile_cmd=("__CLANG__", "-x", "c++", "__SRC__"),
        source_sha256=hashlib.sha256(text.encode()).hexdigest(),
        baseline_compiler="llvmorg-22.1.8",
    )


def _recipe() -> LearnedRecipe:
    return LearnedRecipe(
        recipe_id="r-private",
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


def _diag() -> DiagInfo:
    return DiagInfo(17, "err_gap", "gap", "lib/a.cpp", 1, 1, 0, 0, "")


def test_cli_writes_witness_backed_requests_and_audit(tmp_path, monkeypatch):
    recipes = tmp_path / "recipes.jsonl"
    recipes.write_text(json.dumps(_recipe().to_dict()) + "\n")
    sources = tmp_path / "sources.jsonl"
    sources.write_text(
        json.dumps(_source("lib/a.cpp").to_dict()) + "\n"
        + json.dumps(_source("lib/b.cpp").to_dict()) + "\n"
    )
    out = tmp_path / "requests.jsonl"
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(
        run_build_witness_requests,
        "load_catalog",
        lambda: Catalog([DiagEntry("err_gap", "Error", "gap", "Sema")]),
    )
    monkeypatch.setattr(
        run_build_witness_requests,
        "resolve_diag_ids",
        lambda _names, _bin: {"err_gap": 17},
    )
    monkeypatch.setattr(
        run_build_witness_requests,
        "FuzzlangClangVerifier",
        lambda *_args, **_kwargs: MockVerifier(
            lambda source, _cmd, _path: (
                VerifierResult(False, _diag(), "")
                if "return false;" in source
                else VerifierResult(True, None, "")
            )
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_build_witness_requests.py",
            "--recipes", str(recipes),
            "--clean-sources", str(sources),
            "--clang-bin", "/fake/clang++",
            "--clang-c-bin", "/fake/clang",
            "--diagtool-bin", "/fake/diagtool",
            "--out", str(out),
            "--audit-out", str(audit),
            "--max-targets", "1",
        ],
    )

    assert run_build_witness_requests.main() == 0
    assert "r-private" not in out.read_text()
    assert json.loads(audit.read_text())["retrieval_recipe_id"] == "r-private"


def test_excluded_target_loader_reads_prior_request_names(tmp_path):
    prior = tmp_path / "prior.jsonl"
    prior.write_text('{"diag_name":"err_a"}\n{"diag_name":"err_b"}\n')

    assert run_build_witness_requests._excluded_target_diagnostics([prior]) == {
        "err_a", "err_b",
    }
