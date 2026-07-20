#!/usr/bin/env python3
"""Build leakage-guarded, token-matched SFT construction arms.

The output records remain canonical paired FuzzLang records.  Legacy learned
recipe replay is eligible for the FuzzLang arm only when every referenced
recipe converts to a canonical Injector without changing replay semantics.
The original generation label is retained and the immutable Injector identity
is added as auditable derived provenance.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from gen.fuzzlang_dsl import FuzzLangInjector
from gen.realcorpus.corpus import is_test_path
from repair import run_sft


ARM_METHODS = ("mechanical", "direct_edit", "fuzzlang")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_jsonl(paths: Iterable[str | Path]) -> Iterable[tuple[Path, int, dict]]:
    for raw_path in paths:
        path = Path(raw_path)
        with path.open() as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(f"invalid JSON at {path}:{line_number}: {error}") from error
                if not isinstance(value, dict):
                    raise ValueError(f"JSONL row must be an object at {path}:{line_number}")
                yield path, line_number, value


def _file_report(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    records = sum(1 for line in path.open() if line.strip())
    return {
        "path": str(path),
        "records": records,
        "bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _normalized_text_hash(value: str) -> str:
    return _sha256_text(" ".join(value.split()))


def _paired_source_hash(row: Mapping[str, Any]) -> str:
    return _sha256_text(
        str(row["erroneous_src"]) + "\0" + str(row["corrected_src"])
    )


@dataclass(frozen=True)
class EvalGuard:
    record_ids: frozenset[str]
    source_keys: frozenset[str]
    erroneous_source_hashes: frozenset[str]
    corrected_source_hashes: frozenset[str]
    localized_input_hashes: frozenset[str]
    paired_source_hashes: frozenset[str]

    @classmethod
    def empty(cls) -> "EvalGuard":
        return cls(*(frozenset() for _ in range(6)))


@dataclass(frozen=True)
class Candidate:
    row: dict[str, Any]
    record_id: str
    source_key: str
    diagnostic: str
    rendered_tokens: int
    completion_tokens: int
    localized_input_hash: str
    paired_source_hash: str


def load_stable_diag_ids(paths: Sequence[str | Path]) -> tuple[dict[str, int], dict]:
    """Load diagnostic names having exactly one observed numeric ID."""
    observed: dict[str, set[int]] = {}
    rows = 0
    for path, line_number, row in _read_jsonl(paths):
        rows += 1
        diagnostics = row.get("diagnostics")
        if not isinstance(diagnostics, list):
            raise ValueError(f"missing diagnostics at {path}:{line_number}")
        for diagnostic in diagnostics:
            if not isinstance(diagnostic, dict):
                continue
            name, diag_id = diagnostic.get("diag_name"), diagnostic.get("diag_id")
            if isinstance(name, str) and name and isinstance(diag_id, int):
                observed.setdefault(name, set()).add(diag_id)
    stable = {
        name: next(iter(values))
        for name, values in observed.items()
        if len(values) == 1
    }
    return stable, {
        "records": rows,
        "diagnostics_observed": len(observed),
        "stable_diagnostic_ids": len(stable),
        "ambiguous_diagnostic_ids": sum(len(values) != 1 for values in observed.values()),
        "files": [_file_report(path) for path in paths],
    }


def load_injector_map(
    paths: Sequence[str | Path],
    *,
    diag_ids: Mapping[str, int] | None = None,
) -> tuple[dict[str, FuzzLangInjector], dict[str, Any]]:
    """Convert every portable legacy recipe to its immutable Injector identity."""
    mapping: dict[str, FuzzLangInjector] = {}
    recipe_rows = 0
    portable_rows = 0
    for path, line_number, row in _read_jsonl(paths):
        recipe_rows += 1
        if not row.get("portable", False):
            continue
        portable_rows += 1
        recipe_id = row.get("recipe_id")
        if not isinstance(recipe_id, str) or not recipe_id:
            raise ValueError(f"portable recipe lacks recipe_id at {path}:{line_number}")
        diag_name = row.get("diag_name")
        injector = FuzzLangInjector.from_recipe_dict(
            row,
            diag_id=(diag_ids or {}).get(str(diag_name)),
        )
        previous = mapping.get(recipe_id)
        if previous is not None and previous.injector_id != injector.injector_id:
            raise ValueError(
                f"recipe {recipe_id!r} has conflicting Injector identities: "
                f"{previous.injector_id} != {injector.injector_id}"
            )
        mapping[recipe_id] = injector
    return mapping, {
        "recipe_rows": recipe_rows,
        "portable_recipe_rows": portable_rows,
        "unique_recipe_ids": len(mapping),
        "unique_injector_ids": len({value.injector_id for value in mapping.values()}),
        "with_target_diag_id": sum(value.target_diag_id is not None for value in mapping.values()),
        "files": [_file_report(path) for path in paths],
    }


def _canonical_and_method_gate(
    row: Mapping[str, Any],
    *,
    method: str,
    injector_by_recipe: Mapping[str, FuzzLangInjector],
    location: str,
) -> dict[str, Any]:
    required_strings = ("record_id", "erroneous_src", "corrected_src")
    for key in required_strings:
        if not isinstance(row.get(key), str) or not row[key]:
            raise ValueError(f"{method} row lacks non-empty {key} at {location}")
    if row["erroneous_src"] == row["corrected_src"]:
        raise ValueError(f"paired sources are identical at {location}")
    diagnostics = row.get("diagnostics")
    if not isinstance(diagnostics, list) or not diagnostics:
        raise ValueError(f"{method} row lacks diagnostics at {location}")
    provenance = row.get("provenance")
    if not isinstance(provenance, dict) or not isinstance(provenance.get("detail"), dict):
        raise ValueError(f"{method} row lacks canonical provenance at {location}")
    detail = provenance["detail"]
    origin = provenance.get("origin")
    source_path = detail.get("source_path") or provenance.get("source")
    if not isinstance(source_path, str) or is_test_path(source_path):
        raise ValueError(f"{method} row uses a test or missing source at {location}")

    if method == "mechanical":
        if origin != "mutate" or not isinstance(detail.get("mutation"), str):
            raise ValueError(
                f"Mechanical arm requires origin=mutate and detail.mutation at {location}"
            )
    elif method == "direct_edit":
        if origin != "llm" or detail.get("generator") != "llm_localized_edit":
            raise ValueError(
                "DirectEdit arm requires origin=llm and "
                f"generator=llm_localized_edit at {location}"
            )
    elif method == "fuzzlang":
        if origin != "mutate" or detail.get("strategy") not in {
            "learned_recipe_replay", "fuzzlang_dsl_replay",
        }:
            raise ValueError(
                "FuzzLang arm requires verified recipe/DSL replay provenance at "
                f"{location}"
            )
        recipe_id = detail.get("recipe_id")
        injector = injector_by_recipe.get(str(recipe_id))
        if injector is None:
            raise ValueError(
                f"FuzzLang recipe {recipe_id!r} has no auditable Injector mapping "
                f"at {location}"
            )
        existing_id = detail.get("injector_id")
        if existing_id is not None and existing_id != injector.injector_id:
            raise ValueError(
                f"stored Injector ID disagrees with recipe mapping at {location}"
            )
    else:
        raise ValueError(f"unknown SFT arm: {method}")

    derived = deepcopy(dict(row))
    derived_detail = derived["provenance"]["detail"]
    derived_detail["sft_arm"] = method
    derived_detail["source_split"] = row.get("split")
    if method == "fuzzlang":
        injector = injector_by_recipe[str(detail["recipe_id"])]
        derived_detail.update({
            "injector_id": injector.injector_id,
            "injector_schema": injector.schema,
            "injector_schema_version": injector.schema_version,
            "injector_content_hash": injector.content_hash,
            "injector_mapping": "semantics_preserving_recipe_adapter",
        })
    derived["split"] = "train"
    return derived


def build_eval_guard(
    paths: Sequence[str | Path],
    *,
    context_lines: int = 8,
    max_window_chars: int = 8_000,
    max_edit_chars: int = 2_000,
) -> tuple[EvalGuard, dict[str, Any]]:
    values: dict[str, set[str]] = {
        "record_ids": set(),
        "source_keys": set(),
        "erroneous_source_hashes": set(),
        "corrected_source_hashes": set(),
        "localized_input_hashes": set(),
        "paired_source_hashes": set(),
    }
    rows = 0
    for path, line_number, row in _read_jsonl(paths):
        rows += 1
        try:
            normalized = run_sft._normalize_example(
                row,
                target_format="window-rewrite",
                context_lines=context_lines,
                max_window_chars=max_window_chars,
                max_edit_chars=max_edit_chars,
            )
            source_key = row["provenance"]["source"]
            corrected = row["corrected_src"]
            erroneous = row["erroneous_src"]
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"invalid eval guard row at {path}:{line_number}: {error}") from error
        values["record_ids"].add(str(row["record_id"]))
        values["source_keys"].add(str(source_key))
        values["erroneous_source_hashes"].add(_sha256_text(erroneous))
        values["corrected_source_hashes"].add(_sha256_text(corrected))
        values["localized_input_hashes"].add(_normalized_text_hash(normalized["source"]))
        values["paired_source_hashes"].add(_paired_source_hash(row))
    guard = EvalGuard(*(frozenset(values[name]) for name in (
        "record_ids", "source_keys", "erroneous_source_hashes",
        "corrected_source_hashes", "localized_input_hashes", "paired_source_hashes",
    )))
    report = {"records": rows, "files": [_file_report(path) for path in paths]}
    report.update({name: len(value) for name, value in values.items()})
    return guard, report


def prepare_candidates(
    method: str,
    paths: Sequence[str | Path],
    *,
    tokenizer: Any,
    eval_guard: EvalGuard,
    injector_by_recipe: Mapping[str, FuzzLangInjector],
    max_seq_len: int,
    context_lines: int = 8,
    max_window_chars: int = 8_000,
    max_edit_chars: int = 2_000,
) -> tuple[list[Candidate], Counter]:
    candidates: list[Candidate] = []
    exclusions: Counter = Counter()
    seen_record_ids: set[str] = set()
    seen_pairs: set[str] = set()
    seen_inputs: set[str] = set()
    for path, line_number, raw_row in _read_jsonl(paths):
        location = f"{path}:{line_number}"
        row = _canonical_and_method_gate(
            raw_row,
            method=method,
            injector_by_recipe=injector_by_recipe,
            location=location,
        )
        normalized = run_sft._normalize_example(
            row,
            target_format="window-rewrite",
            context_lines=context_lines,
            max_window_chars=max_window_chars,
            max_edit_chars=max_edit_chars,
        )
        training = run_sft._make_prompt_completion(
            normalized,
            tokenizer=tokenizer,
            chat_template="native",
            target_format="window-rewrite",
        )
        rendered_tokens = len(tokenizer(
            training["prompt"] + training["completion"], truncation=False
        )["input_ids"])
        completion_tokens = len(tokenizer(
            training["completion"], truncation=False
        )["input_ids"])
        if rendered_tokens > max_seq_len:
            raise ValueError(
                f"{method} record {row['record_id']} has {rendered_tokens} tokens, "
                f"exceeding max_seq_len={max_seq_len}; no implicit truncation/drop"
            )

        source_key = str(row["provenance"]["source"])
        record_id = str(row["record_id"])
        input_hash = _normalized_text_hash(normalized["source"])
        pair_hash = _paired_source_hash(row)
        leakage_reason = None
        for reason, present in (
            ("eval_record_id", record_id in eval_guard.record_ids),
            ("eval_source_key", source_key in eval_guard.source_keys),
            ("eval_erroneous_source", _sha256_text(row["erroneous_src"]) in eval_guard.erroneous_source_hashes),
            ("eval_corrected_source", _sha256_text(row["corrected_src"]) in eval_guard.corrected_source_hashes),
            ("eval_localized_input", input_hash in eval_guard.localized_input_hashes),
            ("eval_paired_source", pair_hash in eval_guard.paired_source_hashes),
            ("duplicate_record_id", record_id in seen_record_ids),
            ("duplicate_localized_input", input_hash in seen_inputs),
            ("duplicate_paired_source", pair_hash in seen_pairs),
        ):
            if present:
                leakage_reason = reason
                break
        if leakage_reason:
            exclusions[leakage_reason] += 1
            continue
        seen_record_ids.add(record_id)
        seen_inputs.add(input_hash)
        seen_pairs.add(pair_hash)
        primary = row["diagnostics"][0]
        candidates.append(Candidate(
            row=row,
            record_id=record_id,
            source_key=source_key,
            diagnostic=str(primary.get("diag_name") or ""),
            rendered_tokens=rendered_tokens,
            completion_tokens=completion_tokens,
            localized_input_hash=input_hash,
            paired_source_hash=pair_hash,
        ))
    if not candidates:
        raise ValueError(f"no eligible records remain for {method}")
    return candidates, exclusions


def _select_to_budget(
    candidates: Sequence[Candidate], *, budget: int, seed: int, arm: str,
) -> list[Candidate]:
    if budget <= 0:
        raise ValueError("token budget must be positive")
    ordered = sorted(
        candidates,
        key=lambda candidate: _sha256_text(f"{seed}|{arm}|{candidate.record_id}"),
    )
    selected: list[Candidate] = []
    remaining = budget
    for candidate in ordered:
        if candidate.rendered_tokens <= remaining:
            selected.append(candidate)
            remaining -= candidate.rendered_tokens
    if not selected:
        raise ValueError(f"token budget {budget} cannot fit any {arm} record")
    return selected


def largest_common_count_budget(
    arms: Mapping[str, Sequence[Candidate]],
) -> tuple[int, int]:
    """Return the largest record count whose token ranges intersect.

    For a fixed count, each arm can realize totals between the sum of its
    shortest records and the sum of its longest records.  The returned budget
    is the top of the common interval, maximizing data while allowing the same
    number of examples (and therefore optimizer updates) in every arm.
    """
    if not arms or any(not candidates for candidates in arms.values()):
        raise ValueError("count matching requires non-empty arms")
    ordered_lengths = {
        arm: sorted(candidate.rendered_tokens for candidate in candidates)
        for arm, candidates in arms.items()
    }
    max_count = min(len(values) for values in ordered_lengths.values())
    low_prefix: dict[str, list[int]] = {}
    high_prefix: dict[str, list[int]] = {}
    for arm, values in ordered_lengths.items():
        low = [0]
        high = [0]
        for value in values:
            low.append(low[-1] + value)
        for value in reversed(values):
            high.append(high[-1] + value)
        low_prefix[arm], high_prefix[arm] = low, high
    for count in range(max_count, 0, -1):
        common_low = max(values[count] for values in low_prefix.values())
        common_high = min(values[count] for values in high_prefix.values())
        if common_low <= common_high:
            return count, common_high
    raise ValueError("the SFT arms have no common count/token budget")


def select_count_to_budget(
    candidates: Sequence[Candidate],
    *,
    count: int,
    budget: int,
    seed: int,
    arm: str,
) -> list[Candidate]:
    """Choose exactly ``count`` records with a total at or just below budget."""
    if count <= 0 or count > len(candidates):
        raise ValueError(f"invalid count={count} for {len(candidates)} {arm} records")
    tie_key = lambda candidate: _sha256_text(
        f"{seed}|{arm}|count-match|{candidate.record_id}"
    )
    ordered = sorted(
        candidates,
        key=lambda candidate: (candidate.rendered_tokens, tie_key(candidate)),
    )
    selected = list(ordered[:count])
    unselected = list(ordered[count:])
    total = sum(candidate.rendered_tokens for candidate in selected)
    if total > budget:
        raise ValueError(f"{arm} shortest {count} records exceed budget={budget}")

    while total < budget and unselected:
        gap = budget - total
        best: tuple[int, str, int, int] | None = None
        for selected_index, old in enumerate(selected):
            for unselected_index, new in enumerate(unselected):
                delta = new.rendered_tokens - old.rendered_tokens
                if delta <= 0 or delta > gap:
                    continue
                candidate_key = (delta, tie_key(new), selected_index, unselected_index)
                if best is None or candidate_key[:2] > best[:2]:
                    best = candidate_key
        if best is None:
            break
        delta, _, selected_index, unselected_index = best
        selected[selected_index], unselected[unselected_index] = (
            unselected[unselected_index], selected[selected_index]
        )
        total += delta
    return sorted(selected, key=tie_key)


def _overlap_count(groups: Sequence[set[str]]) -> int:
    seen: set[str] = set()
    overlap: set[str] = set()
    for group in groups:
        overlap.update(seen.intersection(group))
        seen.update(group)
    return len(overlap)


def _write_rows(path: Path, rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return _file_report(path)


def build_matched_arms(
    *,
    arm_paths: Mapping[str, Sequence[str | Path]],
    eval_paths: Sequence[str | Path],
    recipe_paths: Sequence[str | Path],
    tokenizer: Any,
    tokenizer_name: str,
    model_revision: str | None,
    out_dir: str | Path,
    seed: int = 42,
    max_seq_len: int = 1024,
    context_lines: int = 8,
    max_window_chars: int = 8_000,
    max_edit_chars: int = 2_000,
    max_relative_token_gap: float = 0.005,
    diag_evidence_paths: Sequence[str | Path] = (),
    budget_tokens: int | None = None,
    match_record_count: bool = False,
) -> dict[str, Any]:
    if set(arm_paths) != set(ARM_METHODS):
        raise ValueError(f"arm_paths must contain exactly {ARM_METHODS}")
    if not (0 <= max_relative_token_gap < 1):
        raise ValueError("max_relative_token_gap must lie in [0, 1)")
    diag_ids, diag_report = load_stable_diag_ids(diag_evidence_paths) if diag_evidence_paths else ({}, None)
    injector_map, injector_report = load_injector_map(recipe_paths, diag_ids=diag_ids)
    eval_guard, eval_report = build_eval_guard(
        eval_paths,
        context_lines=context_lines,
        max_window_chars=max_window_chars,
        max_edit_chars=max_edit_chars,
    )

    prepared: dict[str, list[Candidate]] = {}
    exclusion_reports: dict[str, Counter] = {}
    for method in ARM_METHODS:
        prepared[method], exclusion_reports[method] = prepare_candidates(
            method,
            arm_paths[method],
            tokenizer=tokenizer,
            eval_guard=eval_guard,
            injector_by_recipe=injector_map,
            max_seq_len=max_seq_len,
            context_lines=context_lines,
            max_window_chars=max_window_chars,
            max_edit_chars=max_edit_chars,
        )
    available_totals = {
        method: sum(candidate.rendered_tokens for candidate in candidates)
        for method, candidates in prepared.items()
    }
    matched_record_count: int | None = None
    if match_record_count:
        if budget_tokens is not None:
            raise ValueError("--budget-tokens cannot be combined with count matching")
        matched_record_count, requested_budget = largest_common_count_budget(prepared)
        selected = {
            method: select_count_to_budget(
                candidates,
                count=matched_record_count,
                budget=requested_budget,
                seed=seed,
                arm=method,
            )
            for method, candidates in prepared.items()
        }
    else:
        requested_budget = budget_tokens or min(available_totals.values())
        if requested_budget > min(available_totals.values()):
            raise ValueError(
                f"requested budget {requested_budget} exceeds smallest arm pool "
                f"({min(available_totals.values())})"
            )
        selected = {
            method: _select_to_budget(
                candidates, budget=requested_budget, seed=seed, arm=method
            )
            for method, candidates in prepared.items()
        }
    selected_totals = {
        method: sum(candidate.rendered_tokens for candidate in candidates)
        for method, candidates in selected.items()
    }
    min_selected, max_selected = min(selected_totals.values()), max(selected_totals.values())
    relative_gap = (max_selected - min_selected) / max_selected
    if relative_gap > max_relative_token_gap:
        raise ValueError(
            f"matched-token gap {relative_gap:.6f} exceeds "
            f"tolerance {max_relative_token_gap:.6f}: {selected_totals}"
        )

    output_dir = Path(out_dir)
    arm_reports: dict[str, Any] = {}
    for method in ARM_METHODS:
        chosen = selected[method]
        output = _write_rows(output_dir / f"{method}.train.jsonl", [item.row for item in chosen])
        arm_reports[method] = {
            "method": method,
            "inputs": [_file_report(path) for path in arm_paths[method]],
            "input_records": sum(report["records"] for report in [_file_report(path) for path in arm_paths[method]]),
            "eligible_records": len(prepared[method]),
            "eligible_distinct_diagnostics": len({
                item.diagnostic for item in prepared[method]
            }),
            "eligible_distinct_source_keys": len({
                item.source_key for item in prepared[method]
            }),
            "eligible_distinct_injectors": len({
                item.row["provenance"]["detail"].get("injector_id")
                for item in prepared[method]
                if item.row["provenance"]["detail"].get("injector_id")
            }),
            "exclusions": dict(sorted(exclusion_reports[method].items())),
            "available_rendered_tokens": available_totals[method],
            "selected_records": len(chosen),
            "selected_rendered_tokens": selected_totals[method],
            "selected_completion_tokens": sum(item.completion_tokens for item in chosen),
            "distinct_diagnostics": len({item.diagnostic for item in chosen}),
            "distinct_source_keys": len({item.source_key for item in chosen}),
            "distinct_injectors": len({
                item.row["provenance"]["detail"].get("injector_id")
                for item in chosen
                if item.row["provenance"]["detail"].get("injector_id")
            }),
            "eval_overlap": {
                "record_ids": 0,
                "source_keys": 0,
                "localized_input_hashes": 0,
                "paired_source_hashes": 0,
            },
            "output": output,
        }

    selected_groups = [selected[method] for method in ARM_METHODS]
    cross_overlap = {
        "record_ids": _overlap_count([{item.record_id for item in group} for group in selected_groups]),
        "source_keys": _overlap_count([{item.source_key for item in group} for group in selected_groups]),
        "localized_input_hashes": _overlap_count([{item.localized_input_hash for item in group} for group in selected_groups]),
        "paired_source_hashes": _overlap_count([{item.paired_source_hash for item in group} for group in selected_groups]),
    }
    # Sharing a correct-source TU across construction arms is an intentional
    # realism control, not evaluation leakage.  The generated repair inputs,
    # paired records, and record identities must still remain disjoint.
    disallowed_overlap = {
        key: value for key, value in cross_overlap.items()
        if key != "source_keys" and value
    }
    if disallowed_overlap:
        raise ValueError(f"selected SFT arms overlap: {disallowed_overlap}")

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "matched-token SFT construction-arm experiment",
        "tokenizer": tokenizer_name,
        "model_revision": model_revision,
        "seed": seed,
        "representation": {
            "chat_template": "native",
            "target_format": "window-rewrite",
            "context_lines": context_lines,
            "max_window_chars": max_window_chars,
            "max_edit_chars": max_edit_chars,
            "max_seq_len": max_seq_len,
            "overlong_policy": "error",
        },
        "token_budget": {
            "matching_unit": "complete rendered prompt plus completion tokens",
            "requested_tokens": requested_budget,
            "max_relative_gap_allowed": max_relative_token_gap,
            "record_count_matched": match_record_count,
            "matched_record_count": matched_record_count,
            "min_selected_tokens": min_selected,
            "max_selected_tokens": max_selected,
            "absolute_gap": max_selected - min_selected,
            "relative_gap": relative_gap,
        },
        "evaluation_guard": eval_report,
        "injector_mapping": injector_report,
        "diagnostic_id_evidence": diag_report,
        "arms": arm_reports,
        "cross_arm_selected_overlap": cross_overlap,
        "cross_arm_source_overlap_allowed": True,
        "uses_paid_api": False,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mechanical", action="append", required=True)
    parser.add_argument("--direct-edit", action="append", required=True)
    parser.add_argument("--fuzzlang", action="append", required=True)
    parser.add_argument("--fuzzlang-recipes", action="append", required=True)
    parser.add_argument("--eval", action="append", required=True)
    parser.add_argument("--diag-evidence", action="append", default=[])
    parser.add_argument("--tokenizer", required=True)
    parser.add_argument("--model-revision")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--budget-tokens", type=int)
    parser.add_argument("--max-seq-len", type=int, default=1024)
    parser.add_argument("--context-lines", type=int, default=8)
    parser.add_argument("--max-window-chars", type=int, default=8_000)
    parser.add_argument("--max-edit-chars", type=int, default=2_000)
    parser.add_argument("--max-relative-token-gap", type=float, default=0.005)
    parser.add_argument(
        "--match-record-count",
        action="store_true",
        help=(
            "Match both record count and rendered tokens, so equal epochs and "
            "batching also imply equal optimizer-update counts."
        ),
    )
    parser.add_argument("--local-files-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        args.tokenizer, local_files_only=args.local_files_only
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    manifest = build_matched_arms(
        arm_paths={
            "mechanical": args.mechanical,
            "direct_edit": args.direct_edit,
            "fuzzlang": args.fuzzlang,
        },
        eval_paths=args.eval,
        recipe_paths=args.fuzzlang_recipes,
        tokenizer=tokenizer,
        tokenizer_name=args.tokenizer,
        model_revision=args.model_revision,
        out_dir=args.out_dir,
        seed=args.seed,
        max_seq_len=args.max_seq_len,
        context_lines=args.context_lines,
        max_window_chars=args.max_window_chars,
        max_edit_chars=args.max_edit_chars,
        max_relative_token_gap=args.max_relative_token_gap,
        diag_evidence_paths=args.diag_evidence,
        budget_tokens=args.budget_tokens,
        match_record_count=args.match_record_count,
    )
    print(json.dumps({
        "manifest": str(Path(args.out_dir) / "manifest.json"),
        "token_budget": manifest["token_budget"],
        "arms": {
            name: {
                "records": value["selected_records"],
                "tokens": value["selected_rendered_tokens"],
            }
            for name, value in manifest["arms"].items()
        },
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
