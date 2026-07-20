from __future__ import annotations

import json
import sys

from gen.fuzzlang_dsl import (
    FUZZLANG_DSL_SCHEMA,
    FUZZLANG_DSL_VERSION,
    FuzzLangInjector,
    ReplayLimits,
)
from gen.realcorpus.run_recipe_replay import main
from gen.realcorpus.tests.test_recipes import _record


def test_fuzzlang_dsl_cli_exports_canonical_injectors_and_manifest(
    tmp_path, monkeypatch,
):
    training = _record(
        "training",
        "int f(){ return value; }",
        "int f(){ return &value; }",
    )
    records = tmp_path / "training.jsonl"
    records.write_text(json.dumps(training.to_dict()) + "\n")
    compile_db = tmp_path / "compile_commands.json"
    compile_db.write_text("[]\n")
    output = tmp_path / "records.jsonl"
    recipes = tmp_path / "recipes.jsonl"
    injectors = tmp_path / "injectors.jsonl"
    manifest = tmp_path / "manifest.json"
    monkeypatch.setattr(sys, "argv", [
        "run_recipe_replay.py",
        "--records", str(records),
        "--compile-db", str(compile_db),
        "--clang-bin", "/unused/clang",
        "--diagtool-bin", "/unused/diagtool",
        "--out", str(output),
        "--recipes-out", str(recipes),
        "--injectors-out", str(injectors),
        "--manifest-out", str(manifest),
        "--replay-engine", "fuzzlang-dsl",
        "--n-files", "0",
    ])

    main()

    recipe_value = json.loads(recipes.read_text().splitlines()[0])
    expected = FuzzLangInjector.from_recipe_dict(
        recipe_value,
        diag_id=training.primary_diagnostic.diag_id,
        limits=ReplayLimits(
            max_edit_chars=256,
            max_candidates=1,
            max_verifications=16,
        ),
    )
    assert expected.target_diag_id == training.primary_diagnostic.diag_id
    assert injectors.read_text() == expected.to_json() + "\n"
    report = json.loads(manifest.read_text())
    assert report["generator"] == "fuzzlang_dsl_replay"
    assert report["injectors"]["schema"] == FUZZLANG_DSL_SCHEMA
    assert report["injectors"]["schema_version"] == FUZZLANG_DSL_VERSION
    assert report["injectors"]["exported"] == 1
    assert report["injectors"]["selected"] == 1
    assert report["injectors"]["with_diag_id"] == 1
    assert report["injectors"]["selected_ids"] == [expected.injector_id]
    assert report["injectors"]["replayed"] is True
    assert report["injectors"]["file"]["records"] == 1


def test_recipe_replay_cli_defaults_remain_legacy(tmp_path, monkeypatch):
    training = _record(
        "training",
        "int f(){ return value; }",
        "int f(){ return &value; }",
    )
    records = tmp_path / "training.jsonl"
    records.write_text(json.dumps(training.to_dict()) + "\n")
    compile_db = tmp_path / "compile_commands.json"
    compile_db.write_text("[]\n")
    output = tmp_path / "records.jsonl"
    manifest = tmp_path / "manifest.json"
    monkeypatch.setattr(sys, "argv", [
        "run_recipe_replay.py",
        "--records", str(records),
        "--compile-db", str(compile_db),
        "--clang-bin", "/unused/clang",
        "--diagtool-bin", "/unused/diagtool",
        "--out", str(output),
        "--manifest-out", str(manifest),
        "--n-files", "0",
    ])

    main()

    report = json.loads(manifest.read_text())
    assert report["generator"] == "learned_recipe_replay"
    assert "injectors" not in report
    assert not list(tmp_path.glob("*.injectors.jsonl"))
