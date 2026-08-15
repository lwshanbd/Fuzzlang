#!/usr/bin/env python3
"""Run experiment E1: FuzzLang Injector versus per-record DirectEdit.

Both arms consume one frozen request file, so the target diagnostics, the
clean non-test real source windows, and the compiler evidence are identical by
construction.  Every model call, compiler invocation, accepted record, and
rejection reason is archived so the comparison is reproducible.

This is a *method experiment*, not a coverage campaign: its records are written
under an experiment strategy label and are deliberately not inputs to the
canonical coverage audit.
"""
from __future__ import annotations

import argparse
import json
import platform
import time
from dataclasses import replace
from pathlib import Path
from typing import Sequence

from foundation.verifier import FuzzlangClangVerifier
from gen.fuzzlang_dsl.code_witness import CodeWitnessRequest
from gen.fuzzlang_dsl.e1_experiment import (
    ArmResult, compare_arms, run_direct_edit_arm, run_injector_arm,
)
from gen.fuzzlang_dsl.local_gemma import (
    DEFAULT_GEMMA_31B_MODEL, DEFAULT_GEMMA_31B_REVISION,
    DEFAULT_GEMMA_31B_SNAPSHOT, LocalGemma31BBackend,
)
from gen.fuzzlang_dsl.request_builder import resolve_diag_ids
from repair.agent.chat_backend import VLLMChatBackend


def load_requests(paths: Sequence[Path]) -> list[CodeWitnessRequest]:
    return [
        CodeWitnessRequest.from_dict(json.loads(line))
        for path in paths
        for line in Path(path).read_text().splitlines() if line.strip()
    ]


def group_requests(
    requests: Sequence[CodeWitnessRequest],
    *,
    primary_project: str,
    sources_per_target: int | None = None,
) -> dict[str, list[CodeWitnessRequest]]:
    """Group by target, deduplicating sources and keeping a stable order.

    The primary project's translation units come first, so the Injector arm's
    evidence windows are always drawn from the same project in every run and
    every other project's sources are held out as cross-project transfer tests
    for both arms alike.
    """
    grouped: dict[str, dict[str, CodeWitnessRequest]] = {}
    for request in requests:
        grouped.setdefault(request.diag_name, {}).setdefault(
            request.source_id, request,
        )
    ordered: dict[str, list[CodeWitnessRequest]] = {}
    for target in sorted(grouped):
        items = sorted(
            grouped[target].values(),
            key=lambda item: (
                item.project != primary_project, item.project, item.source_id,
            ),
        )
        ordered[target] = (
            items if sources_per_target is None else items[:sources_per_target]
        )
    return ordered


def _write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
    ))


def _archive(result: ArmResult, directory: Path) -> None:
    _write_jsonl(directory / "records.jsonl", [r.to_dict() for r in result.records])
    _write_jsonl(directory / "attempts.jsonl", [a.to_dict() for a in result.attempts])
    _write_jsonl(
        directory / "injectors.jsonl",
        [json.loads(injector.to_json()) for injector in result.injectors],
    )
    (directory / "per_target.json").write_text(
        json.dumps(result.per_target, indent=2, sort_keys=True) + "\n"
    )
    (directory / "summary.json").write_text(
        json.dumps(result.summary(), indent=2, sort_keys=True) + "\n"
    )


class _DryRunBackend:
    """Return one deliberately unusable candidate.

    A dry run exercises the clean-source gate, the response parser, the budget
    accounting, and the archive writer without occupying a GPU, so a GPU
    allocation is only spent once the harness itself is known to work.
    """

    def chat(self, *, messages, temperature, max_tokens, n=1, response_format=None):
        del messages, temperature, max_tokens, response_format
        from repair.agent.chat_backend import ChatResponse

        return [ChatResponse(text="dry run: no model was called", output_tokens=0)
                for _ in range(n)]


def served_model_name(base_url: str, *, timeout_s: float = 30.0) -> str:
    """Ask the local endpoint what it actually serves.

    The launcher registers the snapshot under a short name, so hardcoding the
    Hugging Face repository id makes every request fail with HTTP 404.
    """
    import json as _json
    from urllib.request import urlopen

    with urlopen(base_url.rstrip("/") + "/models", timeout=timeout_s) as response:
        served = _json.loads(response.read().decode("utf-8"))
    entries = served.get("data") if isinstance(served, dict) else None
    if not isinstance(entries, list) or not entries:
        raise RuntimeError(f"{base_url} lists no served model")
    name = entries[0].get("id")
    if not isinstance(name, str) or not name:
        raise RuntimeError(f"{base_url} returned a model without an id")
    # Guard against pointing E1 at a smaller checkpoint by accident.
    if "gemma-4-31b-it" not in name.lower():
        raise RuntimeError(
            f"E1 requires the local Gemma-4-31B-it endpoint; it serves {name!r}"
        )
    return name


def _backend(args):
    if args.backend == "dry-run":
        return _DryRunBackend(), None, "dry-run"
    if args.backend == "vllm":
        name = args.model_name or served_model_name(args.base_url)
        return VLLMChatBackend(
            name,
            base_url=args.base_url,
            timeout_s=args.model_timeout,
            max_concurrency=args.vllm_concurrency,
        ), None, name
    backend = LocalGemma31BBackend(args.model_path, seed=args.seed)
    return backend, backend.count_prompt_tokens, DEFAULT_GEMMA_31B_MODEL


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--clang-bin", required=True)
    parser.add_argument("--clang-c-bin", required=True)
    parser.add_argument("--diagtool-bin", required=True)
    parser.add_argument(
        "--arm", choices=("both", "direct_edit", "injector"), default="both",
    )
    parser.add_argument(
        "--backend", choices=("vllm", "local", "dry-run"), default="vllm",
    )
    parser.add_argument(
        "--max-workers", type=int, default=1,
        help="targets processed concurrently; identical in both arms",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--model-path", default=str(DEFAULT_GEMMA_31B_SNAPSHOT))
    parser.add_argument(
        "--model-name",
        help="served model id; discovered from the endpoint when omitted",
    )
    parser.add_argument("--vllm-concurrency", type=int, default=32)
    parser.add_argument("--model-timeout", type=float, default=600.0)
    parser.add_argument(
        "--candidates", type=int, default=4,
        help="sampled candidates per model call; identical in both arms",
    )
    parser.add_argument("--temperature", type=float, default=0.5)
    parser.add_argument(
        "--direct-edit-max-tokens", type=int, default=400,
        help="output ceiling for one DirectEdit patch",
    )
    parser.add_argument(
        "--injector-max-tokens", type=int, default=1200,
        help="output ceiling for one Injector object (a larger artifact)",
    )
    parser.add_argument("--evidence-sources", type=int, default=2)
    parser.add_argument(
        "--primary-project", default="llvm",
        help="project whose sources supply Injector evidence; every other "
             "project is a held-out cross-project transfer test for both arms",
    )
    parser.add_argument("--sources-per-target", type=int, default=None)
    parser.add_argument("--target-limit", type=int, default=None)
    parser.add_argument("--verify-timeout", type=float, default=20.0)
    parser.add_argument("--seed", type=int, default=20260807)
    args = parser.parse_args()

    requests = load_requests(args.requests)
    grouped = group_requests(
        requests, primary_project=args.primary_project,
        sources_per_target=args.sources_per_target,
    )
    if args.target_limit is not None:
        grouped = dict(list(grouped.items())[:args.target_limit])
    if not grouped:
        raise SystemExit("no E1 requests to run")

    # Pin the compiler-assigned DiagID so acceptance checks the numeric ID as
    # well as the name.  Both arms consume the same resolved requests.
    diag_ids = resolve_diag_ids(grouped, args.diagtool_bin)
    grouped = {
        target: [
            replace(request, diag_id=diag_ids.get(target)) for request in items
        ]
        for target, items in grouped.items()
    }

    verifier = FuzzlangClangVerifier(
        args.clang_bin, args.diagtool_bin, timeout_s=args.verify_timeout,
        clang_c_bin=args.clang_c_bin,
    )
    backend, prompt_token_counter, model_name = _backend(args)

    results: list[ArmResult] = []
    started = time.time()
    if args.arm in ("both", "direct_edit"):
        direct = run_direct_edit_arm(
            grouped, backend, verifier, candidates=args.candidates,
            temperature=args.temperature,
            max_tokens=args.direct_edit_max_tokens,
            evidence_sources=args.evidence_sources,
            prompt_token_counter=prompt_token_counter,
            max_workers=args.max_workers,
        )
        _archive(direct, args.output_dir / "direct_edit")
        results.append(direct)
    if args.arm in ("both", "injector"):
        injector = run_injector_arm(
            grouped, backend, verifier, candidates=args.candidates,
            temperature=args.temperature,
            max_tokens=args.injector_max_tokens,
            evidence_sources=args.evidence_sources,
            prompt_token_counter=prompt_token_counter,
            max_workers=args.max_workers,
        )
        _archive(injector, args.output_dir / "injector")
        results.append(injector)

    comparison = compare_arms(results)
    comparison["manifest"] = {
        "schema": "fuzzlang.e1_injector_vs_direct_edit.v1",
        "experiment": "E1",
        "model": {
            "name": DEFAULT_GEMMA_31B_MODEL,
            "served_as": model_name,
            "revision": DEFAULT_GEMMA_31B_REVISION,
        },
        "paid_api_calls": False,
        "llvm_version": "llvmorg-22.1.8",
        "compiler": {
            "clang_bin": args.clang_bin, "clang_c_bin": args.clang_c_bin,
            "diagtool_bin": args.diagtool_bin,
        },
        "config": {
            "arm": args.arm, "candidates": args.candidates,
            "temperature": args.temperature,
            "direct_edit_max_tokens": args.direct_edit_max_tokens,
            "injector_max_tokens": args.injector_max_tokens,
            "evidence_sources": args.evidence_sources,
            "sources_per_target": args.sources_per_target,
            "primary_project": args.primary_project,
            "max_workers": args.max_workers,
            "backend": args.backend,
            "seed": args.seed,
        },
        "inputs": {
            "request_files": [str(path) for path in args.requests],
            "targets": len(grouped),
            "requests": sum(len(items) for items in grouped.values()),
            "targets_without_resolved_diag_id": sorted(
                set(grouped) - set(diag_ids)
            ),
        },
        "host": platform.node(),
        "wall_seconds": round(time.time() - started, 3),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "comparison.json").write_text(
        json.dumps(comparison, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(
        {"arms": comparison["arms"], "manifest": comparison["manifest"]},
        indent=2, sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
