from __future__ import annotations

import hashlib
from subprocess import CompletedProcess

from foundation.diagnostics.catalog import Catalog, DiagEntry
from gen.fuzzlang_dsl.request_builder import (
    build_synthesis_requests,
    resolve_diag_ids,
)
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
        source_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        baseline_compiler="llvmorg-22.1.8",
    )


def _recipe(diag_name: str, recipe_id: str, *, support: int = 1) -> LearnedRecipe:
    return LearnedRecipe(
        recipe_id=recipe_id,
        diag_name=diag_name,
        language="c++",
        operation="replace",
        old_patterns=("true",),
        new_text="false",
        left_context=("return",),
        right_context=(";",),
        portable=True,
        replacement_parts=(("literal", "false"),),
        support=support,
    )


def _catalog(*names: str) -> Catalog:
    return Catalog([
        DiagEntry(
            name=name,
            severity="Error",
            message=f"message for {name}",
            component="Sema",
        )
        for name in names
    ])


def test_builds_gap_request_from_recipe_retrieval_and_two_real_clean_tus():
    recipe = _recipe("err_gap", "recipe-gap")
    result = build_synthesis_requests(
        [recipe],
        [
            _source("lib/a.cpp", "bool a() { return true; }\n"),
            _source("lib/b.cpp", "bool b() { return true; }\n"),
        ],
        _catalog("err_gap"),
        diag_ids={"err_gap": 17},
        max_targets=1,
    )

    assert len(result.requests) == 1
    request = result.requests[0]
    assert request.diag_name == "err_gap"
    assert request.diag_id == 17
    assert request.component == "Sema"
    assert request.evidence.tablegen_definition == (
        'def err_gap : Error<"message for err_gap">;'
    )
    assert len(request.correct_snippets) == 2
    assert all("return true;" in snippet for snippet in request.correct_snippets)
    assert result.audits[0].status == "selected"
    assert result.audits[0].recipe_id == "recipe-gap"
    assert result.audits[0].source_ids == ("llvm:lib/a.cpp", "llvm:lib/b.cpp")

    prompt = build_synthesis_messages(request)[1]["content"]
    assert "recipe-gap" not in prompt
    assert "message for err_gap" in prompt


def test_builder_excludes_covered_targets_and_requires_two_distinct_real_sources():
    covered = _recipe("err_covered", "recipe-covered", support=10)
    insufficient = _recipe("err_insufficient", "recipe-insufficient", support=9)
    result = build_synthesis_requests(
        [covered, insufficient],
        [_source("lib/only.cpp", "bool f() { return true; }\n")],
        _catalog("err_covered", "err_insufficient"),
        covered_diag_names={"err_covered"},
        max_targets=4,
    )

    assert result.requests == ()
    assert [(item.diag_name, item.status) for item in result.audits] == [
        ("err_covered", "skipped_covered"),
        ("err_insufficient", "skipped_no_two_real_snippets"),
    ]


def test_builder_is_deterministic_and_prefers_higher_support_recipe():
    low = _recipe("err_gap", "recipe-low", support=1)
    high = _recipe("err_gap", "recipe-high", support=2)
    alpha = _recipe("err_alpha", "recipe-alpha", support=2)
    sources = [
        _source("lib/a.cpp", "bool a() { return true; }\n"),
        _source("lib/b.cpp", "bool b() { return true; }\n"),
    ]

    result = build_synthesis_requests(
        [low, alpha, high],
        sources,
        _catalog("err_gap", "err_alpha"),
        max_targets=2,
    )

    assert [request.diag_name for request in result.requests] == [
        "err_alpha", "err_gap",
    ]
    assert result.audits[1].recipe_id == "recipe-high"


def test_builder_can_restrict_selection_to_the_current_tablegen_gap_list():
    selected = _recipe("err_selected", "recipe-selected", support=1)
    not_a_gap = _recipe("err_not_a_gap", "recipe-not-a-gap", support=2)
    sources = [
        _source("lib/a.cpp", "bool a() { return true; }\n"),
        _source("lib/b.cpp", "bool b() { return true; }\n"),
    ]

    result = build_synthesis_requests(
        [selected, not_a_gap],
        sources,
        _catalog("err_selected", "err_not_a_gap"),
        eligible_diag_names={"err_selected"},
        max_targets=1,
    )

    assert [request.diag_name for request in result.requests] == ["err_selected"]
    assert result.audits[0].status == "skipped_not_gap"
    assert result.audits[1].status == "selected"


def test_resolve_diag_ids_keeps_only_successful_numeric_compiler_lookups():
    responses = {
        "err_a": CompletedProcess([], 0, "17\n", ""),
        "err_b": CompletedProcess([], 1, "", "not found"),
        "err_c": CompletedProcess([], 0, "not-an-id\n", ""),
    }

    def runner(command, **_kwargs):
        return responses[command[-1]]

    assert resolve_diag_ids(
        ["err_c", "err_a", "err_b"],
        "/fake/diagtool",
        runner=runner,
    ) == {"err_a": 17}
