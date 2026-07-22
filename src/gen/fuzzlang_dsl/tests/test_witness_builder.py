from __future__ import annotations

import hashlib

from foundation.diagnostics.catalog import Catalog, DiagEntry
from foundation.types import DiagInfo, VerifierResult
from foundation.verifier.mock import MockVerifier
from gen.fuzzlang_dsl import witness_builder
from gen.fuzzlang_dsl.witness_builder import build_witness_synthesis_requests
from gen.fuzzlang_dsl.synthesis import build_synthesis_messages
from gen.realcorpus.clean_source_pool import CleanSourceTU
from gen.realcorpus.recipes import LearnedRecipe


def _source(path: str, text: str) -> CleanSourceTU:
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
        recipe_id="recipe-private-to-audit",
        diag_name="err_target",
        language="c++",
        operation="replace",
        old_patterns=("true",),
        new_text="false",
        left_context=("return",),
        right_context=(";",),
        portable=True,
        replacement_parts=(("literal", "false"),),
        support=3,
    )


def _catalog() -> Catalog:
    return Catalog([
        DiagEntry("err_target", "Error", "target message", "Sema"),
    ])


def _diag(name: str, diag_id: int) -> DiagInfo:
    return DiagInfo(
        diag_id=diag_id,
        diag_name=name,
        diag_msg="target message",
        file="lib/a.cpp",
        line=1,
        col=1,
        start_byte=0,
        end_byte=0,
        span_snippet="",
    )


def test_builder_uses_compiler_validated_witness_without_recipe_leakage():
    sources = [
        _source("lib/a.cpp", "bool a() { return true; }\n"),
        _source("lib/b.cpp", "bool b() { return true; }\n"),
    ]

    def policy(source, _cmd, _path):
        if "return false;" in source:
            return VerifierResult(False, _diag("err_target", 17), "typed error")
        return VerifierResult(True, None, "")

    result = build_witness_synthesis_requests(
        [_recipe()],
        sources,
        _catalog(),
        MockVerifier(policy),
        diag_ids={"err_target": 17},
        max_targets=1,
    )

    assert [item.diag_name for item in result.requests] == ["err_target"]
    request = result.requests[0]
    assert request.diag_id == 17
    assert request.evidence.emission_evidence is not None
    assert "compiler-validated" in request.evidence.emission_evidence.lower()
    assert "Correct local code window:" in request.evidence.emission_evidence
    assert "Mutated local code window:" in request.evidence.emission_evidence
    assert "return true;" in request.evidence.emission_evidence
    assert "return false;" in request.evidence.emission_evidence
    assert "recipe-private-to-audit" not in request.evidence.emission_evidence
    assert result.audits[0].status == "selected"
    assert result.audits[0].recipe_id == "recipe-private-to-audit"
    assert result.audits[0].witness_source_id == "llvm:lib/a.cpp"

    prompt = build_synthesis_messages(request)[1]["content"]
    assert "recipe-private-to-audit" not in prompt
    assert "target message" in prompt


def test_builder_rejects_a_witness_with_the_wrong_typed_diagnostic():
    sources = [
        _source("lib/a.cpp", "bool a() { return true; }\n"),
        _source("lib/b.cpp", "bool b() { return true; }\n"),
    ]

    def policy(source, _cmd, _path):
        if "return false;" in source:
            return VerifierResult(False, _diag("err_other", 18), "typed error")
        return VerifierResult(True, None, "")

    result = build_witness_synthesis_requests(
        [_recipe()],
        sources,
        _catalog(),
        MockVerifier(policy),
        diag_ids={"err_target": 17},
        max_targets=1,
    )

    assert result.requests == ()
    assert result.audits[0].status == "skipped_no_compiler_validated_witness"
    assert result.audits[0].observed_diag == "err_other"


def test_builder_defers_targets_when_the_compiler_witness_budget_is_exhausted():
    sources = [
        _source("lib/a.cpp", "bool a() { return true; }\n"),
        _source("lib/b.cpp", "bool b() { return true; }\n"),
    ]
    result = build_witness_synthesis_requests(
        [_recipe()],
        sources,
        _catalog(),
        MockVerifier(lambda _source, _cmd, _path: VerifierResult(True, None, "")),
        diag_ids={"err_target": 17},
        max_targets=1,
        max_witness_verifications=1,
    )

    assert result.requests == ()
    assert result.audits[0].status == "deferred_witness_budget"
    assert result.verification_usage == {
        "max_witness_verifications": 1,
        "used_witness_verifications": 1,
    }


def test_builder_reuses_tokenization_between_snippet_and_witness_search(monkeypatch):
    sources = [
        _source("lib/a.cpp", "bool a() { return true; }\n"),
        _source("lib/b.cpp", "bool b() { return true; }\n"),
    ]
    original = witness_builder.lex_tokens
    calls = 0

    def counted(source):
        nonlocal calls
        calls += 1
        return original(source)

    monkeypatch.setattr(witness_builder, "lex_tokens", counted)
    result = build_witness_synthesis_requests(
        [_recipe()],
        sources,
        _catalog(),
        MockVerifier(
            lambda source, _cmd, _path: (
                VerifierResult(False, _diag("err_target", 17), "")
                if "return false;" in source
                else VerifierResult(True, None, "")
            )
        ),
        diag_ids={"err_target": 17},
        max_targets=1,
    )

    assert len(result.requests) == 1
    assert calls == 2
