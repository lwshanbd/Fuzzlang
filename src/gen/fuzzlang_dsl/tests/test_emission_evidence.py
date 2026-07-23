from __future__ import annotations

from gen.fuzzlang_dsl.emission_evidence import (
    build_emission_index,
    emission_evidence_for,
    load_emission_index,
    write_emission_index,
)


def test_emission_index_collects_clang_sites_and_excludes_test_support(tmp_path):
    root = tmp_path / "clang"
    source = root / "lib" / "Sema" / "SemaExpr.cpp"
    source.parent.mkdir(parents=True)
    source.write_text(
        "void check() {\n"
        "  if (bad)\n"
        "    Diag(loc, diag::err_target) << value;\n"
        "}\n"
    )
    testing = root / "lib" / "Testing" / "TestingSupport.cpp"
    testing.parent.mkdir(parents=True)
    testing.write_text("auto ignored = diag::err_target;\n")

    index = build_emission_index(root)

    assert set(index) == {"err_target"}
    assert len(index["err_target"]) == 1
    assert index["err_target"][0]["path"] == "lib/Sema/SemaExpr.cpp"
    assert "if (bad)" in index["err_target"][0]["snippet"]


def test_emission_index_round_trip_and_bounded_prompt_evidence(tmp_path):
    index = {
        "err_target": (
            {
                "path": "lib/Parse/Parser.cpp",
                "line": 17,
                "snippet": "Diag(Tok, diag::err_target);",
            },
        ),
    }
    path = tmp_path / "emissions.json"

    write_emission_index(path, index)
    loaded = load_emission_index(path)

    assert loaded == index
    evidence = emission_evidence_for(loaded, "err_target")
    assert "lib/Parse/Parser.cpp:17" in evidence
    assert "diag::err_target" in evidence

