#!/usr/bin/env python3
"""Extract learned modifiers and replay them on unseen real LLVM sources.

No model call is made.  Every candidate TU comes from compile_commands.json,
must compile clean before mutation, must not be a test path or a source used by
the recipe exemplars, and every emitted mutant is checked by patched Clang.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from foundation.compile_db import build_clang_argv, load_compile_db
from foundation.record import Record
from foundation.verifier import FuzzlangClangVerifier
from gen.fuzzlang_dsl import (
    FUZZLANG_DSL_SCHEMA,
    FUZZLANG_DSL_VERSION,
    FuzzLangInjector,
    ReplayLimits,
)
from gen.realcorpus.corpus import is_test_path, sanitize_cmd
from gen.realcorpus.finalize import portable_source_path
from gen.realcorpus.recipes import extract_recipes
from gen.realcorpus.replay import replay_source, source_diverse_recipes


_SOURCE_EXTENSIONS = (".c", ".cc", ".cpp", ".cxx", ".c++")


def _load_records(path: Path) -> list[Record]:
    records: list[Record] = []
    with path.open() as stream:
        for line in stream:
            if line.strip():
                records.append(Record.from_dict(json.loads(line)))
    return records


def _write_jsonl(path: Path, values) -> dict:
    sha = hashlib.sha256()
    count = 0
    with path.open("wb") as stream:
        for value in values:
            line = (json.dumps(value, sort_keys=True) + "\n").encode()
            stream.write(line)
            sha.update(line)
            count += 1
    return {
        "path": str(path), "records": count, "bytes": path.stat().st_size,
        "sha256": sha.hexdigest(),
    }


def _write_injector_jsonl(
    path: Path, injectors: list[FuzzLangInjector],
) -> dict:
    """Write byte-stable, canonical FuzzLang DSL JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256()
    with path.open("wb") as stream:
        for injector in injectors:
            line = (injector.to_json() + "\n").encode("utf-8")
            stream.write(line)
            sha.update(line)
    return {
        "path": str(path), "records": len(injectors),
        "bytes": path.stat().st_size, "sha256": sha.hexdigest(),
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Replay learned diagnostic modifiers on unseen real sources."
    )
    ap.add_argument("--records", type=Path, required=True,
                    help="canonical paired Record JSONL used to learn recipes")
    ap.add_argument("--exclude-records", type=Path, action="append", default=[],
                    help="additional Record JSONL whose source TUs must not be replayed")
    ap.add_argument("--compile-db", type=Path, required=True)
    ap.add_argument("--clang-bin", required=True)
    ap.add_argument("--diagtool-bin", required=True)
    ap.add_argument("--out", type=Path, required=True,
                    help="canonical replayed Record JSONL")
    ap.add_argument("--recipes-out", type=Path, default=None)
    ap.add_argument("--injectors-out", type=Path, default=None,
                    help="optional canonical FuzzLang DSL v0 Injector JSONL")
    ap.add_argument("--manifest-out", type=Path, default=None)
    ap.add_argument(
        "--replay-engine", choices=("recipe", "fuzzlang-dsl"), default="recipe",
        help="recipe preserves legacy replay; fuzzlang-dsl replays converted Injectors",
    )
    ap.add_argument("--project", default="llvm")
    ap.add_argument("--source-substr", default="external/llvm-project")
    ap.add_argument("--language", choices=("all", "c", "c++"), default="all")
    ap.add_argument("--n-files", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--context-tokens", type=int, default=2)
    ap.add_argument("--max-edit-chars", type=int, default=256,
                    help="portable recipes cannot replace/insert a larger span")
    ap.add_argument("--max-recipes-per-language", type=int, default=0,
                    help="0 keeps every portable recipe")
    ap.add_argument("--recipe-mode", choices=("all", "bindings"), default="all",
                    help="bindings runs only v2 recipes with identifier metavariables")
    ap.add_argument("--max-candidates-per-recipe", type=int, default=1)
    ap.add_argument("--max-verifications-per-source", type=int, default=16)
    ap.add_argument("--max-records-per-source", type=int, default=3)
    ap.add_argument("--max-instances-per-diagnostic", type=int, default=5,
                    help="global diversity cap; 0 disables")
    ap.add_argument("--max-instances", type=int, default=300)
    ap.add_argument("--exact-only", action="store_true")
    args = ap.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    recipes_out = args.recipes_out or args.out.with_name(
        args.out.stem + ".recipes.jsonl"
    )
    manifest_out = args.manifest_out or args.out.with_name(
        args.out.stem + ".manifest.json"
    )
    injectors_out = args.injectors_out
    if args.replay_engine == "fuzzlang-dsl" and injectors_out is None:
        injectors_out = args.out.with_name(args.out.stem + ".injectors.jsonl")

    print(f"[recipe-replay] loading paired records: {args.records}", flush=True)
    training = _load_records(args.records)
    observed_diag_ids: dict[str, set[int]] = {}
    for record in training:
        diag = record.primary_diagnostic
        if diag and diag.diag_name and diag.diag_id is not None:
            observed_diag_ids.setdefault(diag.diag_name, set()).add(diag.diag_id)
    stable_diag_ids = {
        name: next(iter(values))
        for name, values in observed_diag_ids.items()
        if len(values) == 1
    }
    recipes = extract_recipes(
        training, context_tokens=args.context_tokens,
        max_edit_chars=args.max_edit_chars,
    )
    portable = [recipe for recipe in recipes if recipe.portable]
    selected_recipes = portable
    if args.recipe_mode == "bindings":
        selected_recipes = [
            recipe for recipe in portable
            if any(kind == "binding" for kind, _ in recipe.replacement_parts)
        ]
    print(f"[recipe-replay] recipes={len(recipes)} portable={len(portable)} "
          f"selected={len(selected_recipes)} "
          f"diagnostics={len({r.diag_name for r in selected_recipes})}", flush=True)
    recipes_file = _write_jsonl(recipes_out, (recipe.to_dict() for recipe in recipes))

    portable_injectors: list[FuzzLangInjector] = []
    selected_injectors: list[FuzzLangInjector] = []
    injectors_file = None
    if injectors_out is not None:
        try:
            replay_limits = ReplayLimits(
                max_edit_chars=args.max_edit_chars,
                max_candidates=args.max_candidates_per_recipe,
                max_verifications=args.max_verifications_per_source,
            )
        except ValueError as error:
            ap.error(f"invalid FuzzLang DSL replay limit: {error}")
        portable_injectors = [
            FuzzLangInjector.from_recipe(
                recipe,
                diag_id=stable_diag_ids.get(recipe.diag_name),
                limits=replay_limits,
            )
            for recipe in portable
        ]
        selected_recipe_ids = {recipe.recipe_id for recipe in selected_recipes}
        selected_injectors = [
            injector for injector in portable_injectors
            if injector.source_recipe_id in selected_recipe_ids
        ]
        injectors_file = _write_injector_jsonl(
            injectors_out, portable_injectors
        )

    selected_injector_by_recipe_id = {
        injector.source_recipe_id: injector for injector in selected_injectors
    }

    recipes_by_language = {}
    for language in ("c", "c++"):
        recipes_by_language[language] = [
            recipe for recipe in selected_recipes if recipe.language == language
        ]

    excluded = []
    for path in args.exclude_records:
        excluded.extend(_load_records(path))
    excluded_sources = {
        record.provenance.source for record in [*training, *excluded]
    }
    existing_diags = {
        record.primary_diagnostic.diag_name for record in training
        if record.primary_diagnostic and record.primary_diagnostic.diag_name
    }
    db = load_compile_db(args.compile_db)
    candidates = []
    for path in db:
        lower = path.lower()
        if not lower.endswith(_SOURCE_EXTENSIONS):
            continue
        if args.source_substr and args.source_substr not in path:
            continue
        if is_test_path(path):
            continue
        path_language = "c" if lower.endswith(".c") else "c++"
        if args.language != "all" and path_language != args.language:
            continue
        source_key = f"{args.project}:{portable_source_path(path)}"
        if source_key in excluded_sources:
            continue
        candidates.append(path)
    rng = random.Random(args.seed)
    rng.shuffle(candidates)
    candidates = candidates[:args.n_files]
    print(f"[recipe-replay] unseen non-test candidate TUs={len(candidates)}", flush=True)

    verifier = FuzzlangClangVerifier(
        args.clang_bin, args.diagtool_bin, timeout_s=args.timeout
    )

    def work(path: str):
        try:
            source = Path(path).read_text(errors="replace")
        except OSError:
            return path, None
        entry = db[path]
        command = sanitize_cmd(build_clang_argv(entry, "__CLANG__", "__SRC__"))
        language = "c" if path.lower().endswith(".c") else "c++"
        scheduled = source_diverse_recipes(
            recipes_by_language[language], portable_source_path(path)
        )
        if args.max_recipes_per_language > 0:
            scheduled = scheduled[:args.max_recipes_per_language]
        scheduled_injectors = []
        replay_recipes = scheduled
        if args.replay_engine == "fuzzlang-dsl":
            scheduled_injectors = [
                selected_injector_by_recipe_id[recipe.recipe_id]
                for recipe in scheduled
            ]
            replay_recipes = []
        outcome = replay_source(
            source,
            path=path,
            compile_cmd=command,
            language=language,
            recipes=replay_recipes,
            injectors=scheduled_injectors,
            verifier=verifier,
            project=args.project,
            excluded_sources=excluded_sources,
            max_records=args.max_records_per_source,
            max_candidates_per_recipe=args.max_candidates_per_recipe,
            max_verifications=args.max_verifications_per_source,
            exact_only=args.exact_only,
        )
        return path, outcome

    records: list[Record] = []
    seen_ids: set[str] = set()
    statuses: Counter[str] = Counter()
    candidates_verified = 0
    sources_scanned = 0
    diagnostic_counts: Counter[str] = Counter()
    # Small chunks bound wasted verification after the global record cap.
    chunk_size = max(1, args.workers * 2)
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        for base in range(0, len(candidates), chunk_size):
            chunk = candidates[base:base + chunk_size]
            for _path, outcome in executor.map(work, chunk):
                sources_scanned += 1
                if outcome is None:
                    statuses["source_read_failed"] += 1
                    continue
                statuses[outcome.status] += 1
                candidates_verified += outcome.candidates_verified
                for record in outcome.records:
                    if record.record_id in seen_ids:
                        continue
                    diag_name = record.primary_diagnostic.diag_name
                    if (args.max_instances_per_diagnostic > 0 and
                            diagnostic_counts[diag_name] >=
                            args.max_instances_per_diagnostic):
                        continue
                    seen_ids.add(record.record_id)
                    diagnostic_counts[diag_name] += 1
                    records.append(record)
                    if len(records) >= args.max_instances:
                        break
                if len(records) >= args.max_instances:
                    break
            print(f"[recipe-replay] scanned={sources_scanned} records={len(records)} "
                  f"verified_mutants={candidates_verified}", flush=True)
            if len(records) >= args.max_instances:
                break

    records = records[:args.max_instances]
    output_file = _write_jsonl(args.out, (record.to_dict() for record in records))
    actual_diags = {
        record.primary_diagnostic.diag_name for record in records
        if record.primary_diagnostic and record.primary_diagnostic.diag_name
    }
    novel_diags = sorted(actual_diags - existing_diags)
    manifest = {
        "schema_version": 1,
        "generator": (
            "fuzzlang_dsl_replay" if args.replay_engine == "fuzzlang-dsl"
            else "learned_recipe_replay"
        ),
        "uses_llm_api": False,
        "training": {
            "path": str(args.records),
            "records": len(training),
            "recipe_training_sources": len({r.provenance.source for r in training}),
            "excluded_sources": len(excluded_sources),
            "distinct_diagnostics": len(existing_diags),
            "additional_excluded_records": len(excluded),
            "additional_exclude_paths": [str(path) for path in args.exclude_records],
        },
        "recipes": {
            "extracted": len(recipes),
            "portable": len(portable),
            "portable_diagnostics": len({recipe.diag_name for recipe in portable}),
            "max_edit_chars": args.max_edit_chars,
            "mode": args.recipe_mode,
            "selected": len(selected_recipes),
            "selected_diagnostics": len({r.diag_name for r in selected_recipes}),
            "scheduled_by_language": {
                language: (
                    min(len(values), args.max_recipes_per_language)
                    if args.max_recipes_per_language > 0 else len(values)
                )
                for language, values in recipes_by_language.items()
            },
            "file": recipes_file,
        },
        "replay": {
            "seed": args.seed,
            "candidate_tus": len(candidates),
            "sources_scanned": sources_scanned,
            "statuses": dict(sorted(statuses.items())),
            "mutants_compiled": candidates_verified,
            "records": len(records),
            "sources": len({record.provenance.source for record in records}),
            "distinct_diagnostics": len(actual_diags),
            "novel_diagnostics": novel_diags,
            "exact_target": sum(
                record.provenance.detail["primary_matches_target"] for record in records
            ),
            "near_miss": sum(
                not record.provenance.detail["primary_matches_target"] for record in records
            ),
            "test_sources": sum(
                is_test_path(record.provenance.detail["source_path"])
                for record in records
            ),
            "output": output_file,
        },
        "limits": {
            "n_files": args.n_files,
            "max_instances": args.max_instances,
            "max_records_per_source": args.max_records_per_source,
            "max_instances_per_diagnostic": args.max_instances_per_diagnostic,
            "max_candidates_per_recipe": args.max_candidates_per_recipe,
            "max_verifications_per_source": args.max_verifications_per_source,
            "exact_only": args.exact_only,
            "language": args.language,
        },
        "compiler": {
            "clang_bin": args.clang_bin,
            "diagtool_bin": args.diagtool_bin,
            "required_version": "llvmorg-22.1.8",
        },
    }
    if injectors_file is not None:
        manifest["injectors"] = {
            "schema": FUZZLANG_DSL_SCHEMA,
            "schema_version": FUZZLANG_DSL_VERSION,
            "exported": len(portable_injectors),
            "selected": len(selected_injectors),
            "with_diag_id": sum(
                injector.target_diag_id is not None
                for injector in portable_injectors
            ),
            "selected_diagnostics": len({
                injector.target_diag for injector in selected_injectors
            }),
            "selected_ids": [
                injector.injector_id for injector in selected_injectors
            ],
            "replayed": args.replay_engine == "fuzzlang-dsl",
            "file": injectors_file,
        }
    manifest_out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"[recipe-replay] DONE records={len(records)} "
          f"diagnostics={len(actual_diags)} novel={len(novel_diags)}", flush=True)
    print(f"[recipe-replay] output -> {args.out}", flush=True)
    print(f"[recipe-replay] manifest -> {manifest_out}", flush=True)


if __name__ == "__main__":
    main()
