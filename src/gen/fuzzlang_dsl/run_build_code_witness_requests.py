#!/usr/bin/env python3
"""Bind diagnostic targets to bounded windows from real clean source TUs."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Sequence, TypeVar

from foundation.diagnostics.catalog import Catalog, DiagEntry, load_catalog
from gen.fuzzlang_dsl.breadth_targets import (
    select_uncovered_diagnostics,
    supports_ordinary_cpp_diagnostic_name,
)
from gen.fuzzlang_dsl.code_witness import CodeWitnessRequest
from gen.fuzzlang_dsl.emission_evidence import (
    emission_evidence_for,
    load_emission_index,
)
from gen.mutate._scan import code_mask
from gen.realcorpus.clean_source_pool import load_clean_sources_jsonl


_SourceT = TypeVar("_SourceT")


def _rotated_sources(values: Sequence[_SourceT], *, start: int) -> tuple[_SourceT, ...]:
    """Rotate a source pool so repeated batches see different real TUs first."""
    if start < 0:
        raise ValueError("source start must be non-negative")
    ordered = tuple(values)
    if not ordered:
        return ()
    offset = start % len(ordered)
    return ordered[offset:] + ordered[:offset]


def _source_variant_orders(
    values: Sequence[_SourceT],
    *,
    start: int,
    variants: int,
    stride: int,
) -> tuple[tuple[_SourceT, ...], ...]:
    """Return deterministic source rotations for independent target attempts."""
    if isinstance(variants, bool) or not isinstance(variants, int) or variants <= 0:
        raise ValueError("source variants must be positive")
    if isinstance(stride, bool) or not isinstance(stride, int) or stride <= 0:
        raise ValueError("source variant stride must be positive")
    return tuple(
        _rotated_sources(values, start=start + variant * stride)
        for variant in range(variants)
    )


def _matching_source_candidates(
    sources: Sequence[_SourceT],
    pattern: re.Pattern[str],
    cache: dict[tuple[str, int], tuple[tuple[_SourceT, re.Match[str]], ...]],
    code_masks: dict[str, list[bool]] | None = None,
) -> tuple[tuple[_SourceT, re.Match[str]], ...]:
    """Cache anchor matches for one ordered source pool.

    Large breadth runs reuse a small set of anchor regexes across thousands of
    TableGen names.  Caching prevents repeatedly scanning every full real TU
    for the ubiquitous fallback anchors.
    """
    key = (pattern.pattern, pattern.flags)
    matched = cache.get(key)
    if matched is None:
        masks = code_masks if code_masks is not None else {}

        def first_code_match(source: _SourceT) -> re.Match[str] | None:
            text = source.corrected_src
            source_key = getattr(source, "source_id", text)
            mask = masks.get(source_key)
            if mask is None:
                mask = code_mask(text)
                masks[source_key] = mask
            return next(
                (
                    candidate for candidate in pattern.finditer(text)
                    if all(mask[candidate.start():candidate.end()])
                ),
                None,
            )

        matched = tuple(
            (source, match)
            for source in sources
            for match in (first_code_match(source),)
            if match is not None
        )
        cache[key] = matched
    return matched


def _window(source: str, anchor: int) -> tuple[int, int]:
    left = source.rfind("\n", 0, max(0, anchor - 280)) + 1
    newline = source.find("\n", min(len(source), anchor + 520))
    return left, len(source) if newline < 0 else newline + 1


def _anchor_pattern(diag_name: str) -> re.Pattern[str]:
    """Choose a code shape that gives a diagnostic-specific edit room."""
    if (
        "attribute" in diag_name
        or re.search(r"(?:^|_)attr(?:_|$)", diag_name)
        or "cpu_dispatch" in diag_name
        or "cpu_specific" in diag_name
    ):
        return re.compile(r"(?:\[\[|__attribute__\s*\()")
    if diag_name.startswith("err_asm_") or "_asm_" in diag_name:
        return re.compile(r"\b(?:asm|__asm__)\s*\(")
    if "atomic" in diag_name:
        return re.compile(r"\b(?:__atomic_\w+|atomic(?:_\w+|\s*<))")
    if "builtin" in diag_name:
        return re.compile(r"\b__builtin_\w+\s*\(")
    if "constexpr" in diag_name:
        return re.compile(r"\bconstexpr\b")
    if "complex" in diag_name:
        return re.compile(r"\b(?:complex|Complex)\b")
    if "matrix" in diag_name:
        return re.compile(r"\b(?:matrix|Matrix)\b")
    if "vector" in diag_name:
        return re.compile(r"\b(?:vector|Vector)\b")
    if "abi_tag" in diag_name:
        return re.compile(r"(?:\[\[gnu::abi_tag|__attribute__\s*\(\(abi_tag)")
    if "musttail" in diag_name:
        return re.compile(r"(?:\[\[clang::musttail\]\]|\breturn\b)")
    if "flexible_array" in diag_name:
        return re.compile(r"\[\s*\]")
    if "fold_expression" in diag_name:
        return re.compile(r"\.\.\.")
    if "va_arg" in diag_name:
        return re.compile(r"\b(?:va_arg|__builtin_va_arg)\s*\(")
    if "final_" in diag_name or diag_name.endswith("_final"):
        return re.compile(r"\bfinal\b")
    if "mutable" in diag_name:
        return re.compile(r"\bmutable\b")
    if "nested_name" in diag_name:
        return re.compile(r"::")
    if "redefinition" in diag_name:
        return re.compile(r"\b(?:class|struct|enum|using|typedef)\b")
    if "delete" in diag_name:
        return re.compile(r"\bdelete\b")
    if re.search(r"(?:^|_)new(?:_|$)", diag_name):
        return re.compile(r"\bnew\b")
    if "incomplete" in diag_name:
        return re.compile(r"\b(?:class|struct)\b")
    if "initializer" in diag_name:
        return re.compile(r"(?<![=!<>])=(?!=)")
    if "decltype" in diag_name:
        return re.compile(r"\bdecltype\s*\(")
    if "decomp_decl" in diag_name:
        return re.compile(r"\bauto\s*\[")
    if "deduction_guide" in diag_name:
        return re.compile(r"\)\s*->")
    if "default_not_in_switch" in diag_name:
        return re.compile(r"\bdefault\s*:")
    if "destructor" in diag_name:
        return re.compile(r"~\s*[A-Za-z_]\w*\s*\(")
    if "this_use" in diag_name:
        return re.compile(r"\bthis\b")
    if "thread" in diag_name:
        return re.compile(r"\bthread_local\b")
    if "sign_spec" in diag_name:
        return re.compile(r"\b(?:signed|unsigned)\b")
    if "constraint" in diag_name or "concept" in diag_name:
        return re.compile(r"\b(?:concept|requires)\b")
    if "coroutine" in diag_name or "coawait" in diag_name:
        return re.compile(r"\b(?:co_await|co_return|co_yield)\b")
    if "static_assert" in diag_name:
        return re.compile(r"\bstatic_assert\s*\(")
    if "namespace" in diag_name:
        return re.compile(r"\bnamespace\b")
    if "storageclass" in diag_name or "storage_class" in diag_name:
        return re.compile(r"\b(?:static|extern|register|thread_local|mutable)\b")
    if "typedef" in diag_name:
        return re.compile(r"\btypedef\b")
    if "using_decl" in diag_name or "using_declaration" in diag_name:
        return re.compile(r"\busing\b")
    if "lambda" in diag_name:
        return re.compile(r"\[[^\]\n]*\]\s*(?:<[^>\n]*>\s*)?\(")
    if "template" in diag_name:
        return re.compile(r"\btemplate\s*<")
    if "enumerator" in diag_name or "enum_" in diag_name:
        return re.compile(r"\benum(?:\s+class)?\b")
    if "case_" in diag_name or diag_name.endswith("_case"):
        return re.compile(r"\b(?:case\b[^:\n]*:|switch\s*\()")
    if "condition" in diag_name:
        return re.compile(r"\b(?:if|while|for|switch)\s*\(")
    if "base_specifier" in diag_name:
        return re.compile(r"\b(?:class|struct)\s+[A-Za-z_]\w*[^;{\n]*:")
    if "fn_body" in diag_name or "function_body" in diag_name:
        return re.compile(r"\)\s*(?:const\s*)?(?:noexcept\s*)?(?:->[^ {\n]+)?\s*\{")
    if "call_" in diag_name:
        return re.compile(r"\b[A-Za-z_]\w*\s*\(")
    if "subscript" in diag_name:
        return re.compile(r"\[")
    if "member_reference" in diag_name:
        return re.compile(r"(?:->|\.)")
    if "invalid_operands" in diag_name:
        return re.compile(r"(?:\+|-|\*|/|==|!=|<|>)")
    if "array_size" in diag_name or diag_name.endswith("_negative_array_size"):
        return re.compile(r"\[[^\]\n]+\]")
    if "modifiable_lvalue" in diag_name or "lvalue_casts" in diag_name:
        return re.compile(
            r"\b[A-Za-z_]\w*(?:\s*(?:\[[^\]\n]*\]|\.\w+|->\w+))*\s*=(?!=)"
        )
    if "rparen" in diag_name:
        return re.compile(r"\(")
    if "semi" in diag_name:
        return re.compile(r";")
    return re.compile(r"\breturn\b")


def _anchor_patterns(diag_name: str) -> tuple[re.Pattern[str], ...]:
    """Return a diagnostic-shaped anchor plus a ubiquitous safe fallback."""
    primary = _anchor_pattern(diag_name)
    fallback = re.compile(r"\breturn\b")
    if primary.pattern == fallback.pattern:
        return (primary,)
    return primary, fallback


def _ordered_diagnostic_names_from_jsonl(paths: Sequence[Path]) -> tuple[str, ...]:
    """Load distinct target names in input order from requests or Records."""
    names: list[str] = []
    seen: set[str] = set()
    for path in paths:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            name = value.get("diag_name")
            if not isinstance(name, str):
                name = (
                    value.get("provenance", {})
                    .get("detail", {})
                    .get("target_diag")
                )
            if isinstance(name, str) and name and name not in seen:
                seen.add(name)
                names.append(name)
    return tuple(names)


def _diagnostic_names_from_jsonl(paths: Sequence[Path]) -> set[str]:
    """Load target names from request rows or accepted Record rows."""
    return set(_ordered_diagnostic_names_from_jsonl(paths))


def _successful_diagnostic_names_from_attempts(
    paths: Sequence[Path],
) -> tuple[str, ...]:
    """Load distinct targets that previously reached the exact compiler goal.

    An exact-but-undistillable witness remains useful for a new source attempt:
    it proves that the compiler target is reachable even if its earlier edit
    could not be represented by the narrow lexical Injector language.
    """
    accepted = {"exact_target", "exact_target_not_distillable"}
    names: list[str] = []
    seen: set[str] = set()
    for path in paths:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            name = value.get("diag_name")
            if (
                value.get("status") in accepted
                and isinstance(name, str)
                and name
                and name not in seen
            ):
                seen.add(name)
                names.append(name)
    return tuple(names)


def _attempted_diagnostic_names_from_attempts(
    paths: Sequence[Path],
) -> tuple[str, ...]:
    """Load prior ordinary-mode targets without rereading large source requests."""
    names: list[str] = []
    seen: set[str] = set()
    for path in paths:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            name = value.get("diag_name")
            if (
                value.get("status") != "unsupported_ordinary_cpp_mode"
                and isinstance(name, str)
                and name
                and name not in seen
            ):
                seen.add(name)
                names.append(name)
    return tuple(names)


def _failed_diagnostic_names_from_attempts(
    paths: Sequence[Path],
) -> tuple[str, ...]:
    """Return ordinary targets that have never reached an exact witness.

    New source variants are most valuable for genuine misses, rather than
    targets already shown reachable by an exact compiler witness.  First-seen
    order preserves the upstream diagnostic-priority ordering.
    """
    attempted: list[str] = []
    seen: set[str] = set()
    exact: set[str] = set()
    for path in paths:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            name = value.get("diag_name")
            status = value.get("status")
            if (
                not isinstance(name, str)
                or not name
                or status == "unsupported_ordinary_cpp_mode"
            ):
                continue
            if name not in seen:
                seen.add(name)
                attempted.append(name)
            if status in {"exact_target", "exact_target_not_distillable"}:
                exact.add(name)
    return tuple(name for name in attempted if name not in exact)


def _failed_target_slice(
    names: Sequence[str], *, offset: int, limit: int | None,
) -> tuple[str, ...]:
    """Select a deterministic disjoint slice from ordered failed targets."""
    if offset < 0:
        raise ValueError("failed target offset must be non-negative")
    if limit is not None and limit <= 0:
        raise ValueError("failed target limit must be positive")
    values = tuple(names)[offset:]
    return values if limit is None else values[:limit]


def _observed_diagnostic_names_from_attempts(
    paths: Sequence[Path], *, min_count: int,
) -> tuple[str, ...]:
    """Rank compiler-emitted wrong-target diagnostics by observed reachability."""
    if min_count <= 0:
        raise ValueError("minimum observed count must be positive")
    counts: Counter[str] = Counter()
    for path in paths:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            name = value.get("observed_diag")
            if (
                value.get("status") == "rejected"
                and isinstance(name, str)
                and name
            ):
                counts[name] += 1
    return tuple(
        name for name, count in sorted(
            counts.items(), key=lambda item: (-item[1], item[0]),
        )
        if count >= min_count
    )


def _diagnostic_names_from_audits(paths: Sequence[Path]) -> set[str]:
    """Load only Injector-backed diagnostic names from strict audit reports."""
    names: set[str] = set()
    for path in paths:
        value = json.loads(path.read_text())
        if value.get("schema") != "fuzzlang.verified_injector_coverage_audit.v1":
            raise ValueError(f"unsupported strict coverage audit: {path}")
        verified = value.get("verified_diagnostic_names")
        if (
            not isinstance(verified, list)
            or any(not isinstance(name, str) or not name for name in verified)
        ):
            raise ValueError(
                f"strict coverage audit has invalid diagnostic names: {path}"
            )
        names.update(verified)
    return names


def _resolve_target_entries(
    catalog: Catalog,
    *,
    explicit_names: Sequence[str],
    auto_uncovered_limit: int | None,
    covered: set[str],
    attempted: set[str],
) -> tuple[DiagEntry, ...]:
    """Resolve either explicit targets or a coverage-first TableGen gap slice."""
    if explicit_names and auto_uncovered_limit is not None:
        raise ValueError("--diag-name and --auto-uncovered-limit are exclusive")
    if not explicit_names and auto_uncovered_limit is None:
        raise ValueError("provide --diag-name or --auto-uncovered-limit")
    if auto_uncovered_limit is not None:
        return select_uncovered_diagnostics(
            catalog.entries,
            covered=covered,
            attempted=attempted,
            limit=auto_uncovered_limit,
        )
    entries: list[DiagEntry] = []
    for name in explicit_names:
        entry = catalog.by_name.get(name)
        if entry is None or not entry.is_error:
            raise ValueError(f"target is not a catalog error: {name}")
        if (
            not entry.message.strip()
            or not supports_ordinary_cpp_diagnostic_name(entry.name)
        ):
            continue
        entries.append(entry)
    return tuple(entries)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean-sources", type=Path, required=True)
    parser.add_argument("--catalog-dir", required=True)
    parser.add_argument(
        "--emission-index", type=Path,
        help="optional cached Clang diagnostic emission-site index",
    )
    parser.add_argument("--diag-name", action="append", default=[])
    parser.add_argument(
        "--retry-requests", type=Path, action="append", default=[],
        help="retry target diagnostics from these request JSONLs on new sources",
    )
    parser.add_argument(
        "--successful-attempts", type=Path, action="append", default=[],
        help="retry targets with a prior exact compiler witness on new sources",
    )
    parser.add_argument(
        "--attempted-targets", type=Path, action="append", default=[],
        help="retry any prior ordinary-mode target from compact attempt logs",
    )
    parser.add_argument(
        "--failed-attempts", type=Path, action="append", default=[],
        help="retry only prior targets with no exact witness on a new source",
    )
    parser.add_argument(
        "--failed-limit", type=int,
        help="cap the selected failed-target retry slice",
    )
    parser.add_argument(
        "--failed-offset", type=int, default=0,
        help="skip this many ordered failed targets before applying the limit",
    )
    parser.add_argument(
        "--observed-attempts", type=Path, action="append", default=[],
        help="prior attempts whose compiler-emitted wrong-target diagnostics are ranked",
    )
    parser.add_argument(
        "--observed-min-count", type=int, default=1,
        help="minimum prior compiler observations for an observed-diagnostic target",
    )
    parser.add_argument(
        "--observed-limit", type=int,
        help="cap ranked observed-diagnostic targets after coverage exclusion",
    )
    parser.add_argument(
        "--auto-uncovered-limit", type=int,
        help="select this many unattempted Lex/Parse/Sema TableGen gaps",
    )
    parser.add_argument(
        "--covered-records", type=Path, action="append", default=[],
        help="accepted Record JSONL whose target diagnostics are already covered",
    )
    parser.add_argument(
        "--covered-audit", type=Path, action="append", default=[],
        help="strict Injector-backed coverage audit whose targets are covered",
    )
    parser.add_argument(
        "--attempted-requests", type=Path, action="append", default=[],
        help="prior request JSONL whose diagnostics should not be selected again",
    )
    parser.add_argument(
        "--exclude-attempted-targets", type=Path, action="append", default=[],
        help="compact attempt logs whose diagnostic targets should not be selected again",
    )
    parser.add_argument(
        "--source-start", type=int, default=0,
        help="rotation offset into the verified source pool for this batch",
    )
    parser.add_argument(
        "--source-variants", type=int, default=1,
        help="bind each target to this many distinct real source TUs",
    )
    parser.add_argument(
        "--source-variant-stride", type=int, default=211,
        help="source-pool rotation between target variants",
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--manifest-out", type=Path)
    args = parser.parse_args()
    if args.source_start < 0:
        parser.error("--source-start must be non-negative")
    if args.source_variants <= 0:
        parser.error("--source-variants must be positive")
    if args.source_variant_stride <= 0:
        parser.error("--source-variant-stride must be positive")
    if args.auto_uncovered_limit is not None and args.auto_uncovered_limit <= 0:
        parser.error("--auto-uncovered-limit must be positive")
    if args.observed_min_count <= 0:
        parser.error("--observed-min-count must be positive")
    if args.observed_limit is not None and args.observed_limit <= 0:
        parser.error("--observed-limit must be positive")
    if args.failed_limit is not None and args.failed_limit <= 0:
        parser.error("--failed-limit must be positive")
    if args.failed_offset < 0:
        parser.error("--failed-offset must be non-negative")
    catalog = load_catalog(args.catalog_dir)
    emission_index = (
        load_emission_index(args.emission_index)
        if args.emission_index is not None
        else {}
    )
    covered = _diagnostic_names_from_jsonl(args.covered_records)
    try:
        covered.update(_diagnostic_names_from_audits(args.covered_audit))
    except ValueError as error:
        parser.error(str(error))
    attempted = _diagnostic_names_from_jsonl(args.attempted_requests)
    attempted.update(_attempted_diagnostic_names_from_attempts(
        args.exclude_attempted_targets,
    ))
    modes = sum((
        bool(args.diag_name),
        args.auto_uncovered_limit is not None,
        bool(args.retry_requests),
        bool(args.successful_attempts),
        bool(args.attempted_targets),
        bool(args.failed_attempts),
        bool(args.observed_attempts),
    ))
    if modes != 1:
        parser.error(
            "choose exactly one target mode: --diag-name, "
            "--auto-uncovered-limit, --retry-requests, or "
            "--successful-attempts, --attempted-targets, --failed-attempts, "
            "or --observed-attempts"
        )
    explicit_names = tuple(args.diag_name)
    if args.retry_requests:
        explicit_names = tuple(
            name
            for name in _ordered_diagnostic_names_from_jsonl(args.retry_requests)
            if name not in covered
        )
    if args.successful_attempts:
        explicit_names = tuple(
            name
            for name in _successful_diagnostic_names_from_attempts(
                args.successful_attempts,
            )
            if name not in covered
        )
    if args.attempted_targets:
        explicit_names = tuple(
            name
            for name in _attempted_diagnostic_names_from_attempts(
                args.attempted_targets,
            )
            if name not in covered
        )
    if args.failed_attempts:
        failed_names = tuple(
            name
            for name in _failed_diagnostic_names_from_attempts(
                args.failed_attempts,
            )
            if name not in covered
        )
        explicit_names = _failed_target_slice(
            failed_names,
            offset=args.failed_offset,
            limit=args.failed_limit,
        )
    if args.observed_attempts:
        explicit_names = tuple(
            name for name in _observed_diagnostic_names_from_attempts(
                args.observed_attempts,
                min_count=args.observed_min_count,
            )
            if name not in covered
        )
        if args.observed_limit is not None:
            explicit_names = explicit_names[:args.observed_limit]
    if (
        args.retry_requests
        or args.successful_attempts
        or args.attempted_targets
        or args.failed_attempts
        or args.observed_attempts
    ) and not explicit_names:
        targets = ()
    else:
        try:
            targets = _resolve_target_entries(
                catalog,
                explicit_names=explicit_names,
                auto_uncovered_limit=args.auto_uncovered_limit,
                covered=covered,
                attempted=attempted,
            )
        except ValueError as error:
            parser.error(str(error))
    sources = [
        source for source in load_clean_sources_jsonl(args.clean_sources)
        if source.language == "c++"
    ]
    source_orders = _source_variant_orders(
        sources,
        start=args.source_start,
        variants=args.source_variants,
        stride=args.source_variant_stride,
    )
    requests: list[CodeWitnessRequest] = []
    used_global: set[str] = set()
    used_by_target: dict[str, set[str]] = {}
    code_masks: dict[str, list[bool]] = {}
    for sources_for_variant in source_orders:
        anchor_cache: dict[
            tuple[str, int], tuple[tuple[object, re.Match[str]], ...],
        ] = {}
        for entry in targets:
            target_used = used_by_target.setdefault(entry.name, set())

            def select(
                pattern: re.Pattern[str],
                *,
                require_globally_new: bool,
            ):
                return next(
                    (
                        (item, match)
                        for item, match in _matching_source_candidates(
                            sources_for_variant, pattern, anchor_cache, code_masks,
                        )
                        if item.source_id not in target_used
                        and (
                            not require_globally_new
                            or item.source_id not in used_global
                        )
                    ),
                    None,
                )

            selected = None
            for pattern in _anchor_patterns(entry.name):
                selected = select(pattern, require_globally_new=True)
                if selected is None:
                    selected = select(pattern, require_globally_new=False)
                if selected is not None:
                    break
            if selected is None:
                raise ValueError(
                    "not enough distinct real C++ sources contain any anchor for "
                    f"{entry.name}"
                )
            source, match = selected
            target_used.add(source.source_id)
            used_global.add(source.source_id)
            anchor = match.start()
            start, end = _window(source.corrected_src, anchor)
            tablegen = (
                f"def {entry.name} : {entry.severity}<"
                f"{json.dumps(entry.message, ensure_ascii=False)}>"
                + (", DefaultError" if entry.default_error else "") + ";"
            )
            requests.append(CodeWitnessRequest(
                diag_name=entry.name,
                diag_id=None,
                diag_message=entry.message,
                language=source.language,
                tablegen_definition=tablegen,
                source_id=source.source_id,
                source_path=source.source_path,
                project=source.project,
                compile_cmd=source.compile_cmd,
                corrected_src=source.corrected_src,
                window_start=start,
                window_end=end,
                emission_evidence=emission_evidence_for(
                    emission_index, entry.name,
                ),
            ))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(
        json.dumps(item.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
        for item in requests
    ))
    if args.manifest_out is not None:
        args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
        args.manifest_out.write_text(json.dumps({
            "schema": "fuzzlang.coverage_first_code_witness_requests",
            "llvm_version": "llvmorg-22.1.8",
            "counts": {
                "requests": len(requests),
                "covered_diagnostics_excluded": len(covered),
                "attempted_diagnostics_excluded": len(attempted),
                "targets_with_emission_evidence": sum(
                    request.emission_evidence is not None for request in requests
                ),
                "source_variants": args.source_variants,
            },
            "target_diagnostics": [entry.name for entry in targets],
        }, sort_keys=True) + "\n")
    print(f"[code-witness-requests] requests={len(requests)} uses_llm_api=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
