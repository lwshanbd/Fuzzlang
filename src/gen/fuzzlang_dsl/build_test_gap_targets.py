#!/usr/bin/env python3
"""Derive the current Clang-test-reachable strict-coverage gap list.

Clang regression tests are evidence that a diagnostic can be triggered; they
are never copied to this output as a dataset source.  This utility only
materializes diagnostic *names* for a subsequent Injector-synthesis campaign.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Sequence

from foundation.diagnostics.catalog import Catalog, load_catalog
from gen.fuzzlang_dsl.breadth_targets import (
    is_feature_specific_diagnostic_name,
    supports_default_diagnostic_name,
)


def _read_names(paths: Sequence[Path]) -> set[str]:
    names: set[str] = set()
    for path in paths:
        for raw in path.read_text(encoding="utf-8").splitlines():
            name = raw.strip()
            if name and not name.startswith("#"):
                names.add(name)
    return names


def test_reachable_uncovered_names(
    *, test_reachable: set[str], strict_audit: dict,
) -> list[str]:
    """Return ordered test-reachable names absent from a strict audit."""
    covered = strict_audit.get("verified_diagnostic_names")
    if not isinstance(covered, list) or not all(
        isinstance(name, str) for name in covered
    ):
        raise ValueError("strict audit must contain verified_diagnostic_names")
    return sorted(test_reachable - set(covered))


def catalog_error_names(names: Sequence[str], catalog: Catalog) -> list[str]:
    """Keep only TableGen diagnostics in the core error denominator.

    Clang regression scans also observe warnings and extensions promoted by
    test flags.  They are useful trigger evidence, but cannot become a core
    FuzzLang coverage type, whose denominator is the catalog's error entries.
    """
    return [
        name for name in names
        if (entry := catalog.by_name.get(name)) is not None and entry.is_error
    ]


def compatible_names(
    names: Sequence[str],
    *,
    language: str | None,
    cpp_standard: str,
    c_standard: str,
    feature_mode: str,
    feature_specific_only: bool,
) -> list[str]:
    """Keep targets compatible with a verified real-source compiler mode."""
    if language is None:
        return list(names)
    filter_language = {
        "objective-c": "c",
        "objective-c++": "c++",
    }.get(language, language)
    return [
        name for name in names
        if supports_default_diagnostic_name(
            name,
            language=filter_language,
            cpp_standard=cpp_standard,
            c_standard=c_standard,
            feature_mode=feature_mode,
        )
        and (
            not feature_specific_only
            or is_feature_specific_diagnostic_name(
                name, feature_mode=feature_mode,
            )
        )
    ]


_PLAIN_STANDARD_ALIASES = {
    "c++98": frozenset({"c++98", "c++03"}),
    "c++11": frozenset({"c++11", "c++0x"}),
    "c++14": frozenset({"c++14", "c++1y"}),
    "c++17": frozenset({"c++17", "c++1z"}),
    "c++20": frozenset({"c++20", "c++2a"}),
    "c++23": frozenset({"c++23", "c++2b"}),
    "c++2c": frozenset({"c++2c", "c++26"}),
    "c99": frozenset({"c99", "c9x"}),
    "c11": frozenset({"c11", "c1x"}),
    "c17": frozenset({"c17", "c18"}),
    "c23": frozenset({"c23", "c2x"}),
}


def _trigger_configs(paths: Sequence[Path]) -> dict[str, list[tuple[str, ...]]]:
    """Load test-derived frontend configurations without retaining test code."""
    configs: dict[str, list[tuple[str, ...]]] = {}
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("trigger_configs", {})
        if not isinstance(rows, dict):
            raise ValueError(f"trigger config file lacks trigger_configs: {path}")
        for name, values in rows.items():
            if not isinstance(name, str) or not isinstance(values, list):
                continue
            bucket = configs.setdefault(name, [])
            for value in values:
                if not isinstance(value, list) or not all(
                    isinstance(flag, str) for flag in value
                ):
                    continue
                flags = tuple(value)
                if flags not in bucket:
                    bucket.append(flags)
    return configs


def _is_plain_driver_config(
    config: Sequence[str], *, language: str, standard: str,
) -> bool:
    """Whether one test trigger needs only an ordinary language standard."""
    flags = [
        flag for flag in config
        if flag not in {"__CLANG__", "__SRC__", "-fsyntax-only"}
    ]
    aliases = _PLAIN_STANDARD_ALIASES[standard]
    if len(flags) != 3 or "-x" not in flags:
        return False
    language_index = flags.index("-x")
    if language_index + 1 >= len(flags) or flags[language_index + 1] != language:
        return False
    return any(flag == f"-std={alias}" for flag in flags for alias in aliases)


def plain_trigger_compatible_names(
    names: Sequence[str], *, trigger_configs: dict[str, list[tuple[str, ...]]],
    language: str, standard: str,
) -> list[str]:
    """Retain names with a direct test trigger under no feature/target flags."""
    return [
        name for name in names
        if any(
            _is_plain_driver_config(config, language=language, standard=standard)
            for config in trigger_configs.get(name, [])
        )
    ]


def _is_bare_driver_language_config(config: Sequence[str], *, language: str) -> bool:
    """Whether a driver trigger needs only the requested frontend language."""
    flags = [
        flag for flag in config
        if flag not in {"__CLANG__", "__SRC__", "-fsyntax-only"}
    ]
    return flags == ["-x", language]


def bare_driver_language_compatible_names(
    names: Sequence[str], *, trigger_configs: dict[str, list[tuple[str, ...]]],
    language: str,
) -> list[str]:
    """Keep diagnostics whose test evidence has no feature or target flags."""
    return [
        name for name in names
        if any(
            _is_bare_driver_language_config(config, language=language)
            for config in trigger_configs.get(name, [])
        )
    ]


def _is_standard_only_config(
    config: Sequence[str], *, language: str, standard: str,
) -> bool:
    """Whether a test trigger needs only the language standard in cc1 mode.

    Regression tests frequently invoke ``-cc1`` directly and pass a local
    resource directory.  Those implementation details are not part of the
    trigger condition for a real, clean source TU.  This deliberately accepts
    only the standard (and an optional matching ``-x`` language); any target,
    feature, macro, warning, or other flag keeps the target out of this route.
    """
    flags: list[str] = []
    index = 0
    while index < len(config):
        flag = config[index]
        if flag in {"__CLANG__", "__SRC__", "-fsyntax-only", "-cc1"}:
            index += 1
            continue
        if flag == "-resource-dir":
            index += 2
            continue
        flags.append(flag)
        index += 1
    aliases = _PLAIN_STANDARD_ALIASES[standard]
    if len(flags) == 1:
        return flags[0] in {f"-std={alias}" for alias in aliases}
    if len(flags) != 3 or flags[0] != "-x" or flags[1] != language:
        return False
    return flags[2] in {f"-std={alias}" for alias in aliases}


def standard_trigger_compatible_names(
    names: Sequence[str], *, trigger_configs: dict[str, list[tuple[str, ...]]],
    language: str, standard: str,
) -> list[str]:
    """Retain targets whose cc1 test trigger needs only a language standard."""
    return [
        name for name in names
        if any(
            _is_standard_only_config(config, language=language, standard=standard)
            for config in trigger_configs.get(name, [])
        )
    ]


def trigger_flag_compatible_names(
    names: Sequence[str], *, trigger_configs: dict[str, list[tuple[str, ...]]],
    required_flags: Sequence[str],
) -> list[str]:
    """Retain names whose test trigger contains every required frontend flag."""
    required = frozenset(required_flags)
    return [
        name for name in names
        if any(required.issubset(config) for config in trigger_configs.get(name, []))
    ]


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def _trigger_flag(value: str) -> str:
    """Accept a frontend flag name without requiring shell-hostile ``=-`` syntax."""
    if not value:
        raise argparse.ArgumentTypeError("trigger flag must be non-empty")
    return value if value.startswith("-") else "-" + value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-reachable", type=Path, action="append", required=True)
    parser.add_argument("--strict-audit", type=Path, required=True)
    parser.add_argument(
        "--catalog-dir", type=Path,
        help=(
            "optional TableGen catalog directory; when present, retain only "
            "core catalog error diagnostics before routing"
        ),
    )
    parser.add_argument(
        "--exclude-name-file", type=Path, action="append", default=[],
        help="diagnostic names already queued by an in-flight campaign",
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--manifest-out", type=Path)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=_positive_int)
    parser.add_argument(
        "--language", choices=("c", "c++", "objective-c", "objective-c++"),
    )
    parser.add_argument(
        "--cpp-standard", choices=(
            "c++98", "c++11", "c++14", "c++17", "c++20", "c++23", "c++2c",
        ),
        default="c++23",
    )
    parser.add_argument(
        "--c-standard", choices=("c99", "c11", "c17", "c23"),
        default="c17",
    )
    parser.add_argument(
        "--feature-mode", choices=(
            "ordinary", "openmp", "blocks", "openacc", "objc", "modules",
            "preprocessor", "target",
        ), default="ordinary",
    )
    parser.add_argument("--feature-specific-only", action="store_true")
    parser.add_argument(
        "--trigger-config", type=Path, action="append", default=[],
        help="test-scan JSON with trigger_configs; names/configs only are read",
    )
    parser.add_argument("--plain-driver-language", choices=("c", "c++"))
    parser.add_argument(
        "--plain-driver-standard", choices=tuple(_PLAIN_STANDARD_ALIASES),
    )
    parser.add_argument(
        "--standard-trigger-language", choices=("c", "c++"),
        help=(
            "accept a test cc1 trigger only when it needs no condition beyond "
            "the selected language standard"
        ),
    )
    parser.add_argument(
        "--standard-trigger-standard", choices=tuple(_PLAIN_STANDARD_ALIASES),
    )
    parser.add_argument(
        "--bare-driver-language", choices=("c", "c++", "objective-c", "objective-c++"),
        help="accept a driver test trigger only when it needs exactly -x <language>",
    )
    parser.add_argument(
        "--require-trigger-flag", type=_trigger_flag, action="append", default=[],
        help="required test RUN frontend flag, e.g. fopenmp or fblocks",
    )
    args = parser.parse_args(argv)
    if args.offset < 0:
        parser.error("--offset must be non-negative")
    if bool(args.plain_driver_language) != bool(args.plain_driver_standard):
        parser.error(
            "--plain-driver-language and --plain-driver-standard must be used together",
        )
    if args.plain_driver_language and not args.trigger_config:
        parser.error("--plain-driver-* requires at least one --trigger-config")
    if bool(args.standard_trigger_language) != bool(args.standard_trigger_standard):
        parser.error(
            "--standard-trigger-language and --standard-trigger-standard must be used together",
        )
    if args.standard_trigger_language and not args.trigger_config:
        parser.error("--standard-trigger-* requires at least one --trigger-config")
    if args.bare_driver_language and not args.trigger_config:
        parser.error("--bare-driver-language requires at least one --trigger-config")
    if sum(bool(value) for value in (
        args.plain_driver_language,
        args.standard_trigger_language,
        args.bare_driver_language,
    )) > 1:
        parser.error("choose at most one test-trigger compatibility mode")
    if args.require_trigger_flag and not args.trigger_config:
        parser.error("--require-trigger-flag requires at least one --trigger-config")

    test_reachable = _read_names(args.test_reachable)
    strict_audit = json.loads(args.strict_audit.read_text(encoding="utf-8"))
    strict_gap_names = test_reachable_uncovered_names(
        test_reachable=test_reachable, strict_audit=strict_audit,
    )
    excluded_names = _read_names(args.exclude_name_file)
    all_gap_names = [
        name for name in strict_gap_names if name not in excluded_names
    ]
    if args.catalog_dir is not None:
        all_gap_names = catalog_error_names(
            all_gap_names, load_catalog(args.catalog_dir),
        )
    names = compatible_names(
        all_gap_names,
        language=args.language,
        cpp_standard=args.cpp_standard,
        c_standard=args.c_standard,
        feature_mode=args.feature_mode,
        feature_specific_only=args.feature_specific_only,
    )
    trigger_configs = (
        _trigger_configs(args.trigger_config) if args.trigger_config else {}
    )
    if args.plain_driver_language:
        names = plain_trigger_compatible_names(
            names,
            trigger_configs=trigger_configs,
            language=args.plain_driver_language,
            standard=args.plain_driver_standard,
        )
    if args.standard_trigger_language:
        names = standard_trigger_compatible_names(
            names,
            trigger_configs=trigger_configs,
            language=args.standard_trigger_language,
            standard=args.standard_trigger_standard,
        )
    if args.bare_driver_language:
        names = bare_driver_language_compatible_names(
            names,
            trigger_configs=trigger_configs,
            language=args.bare_driver_language,
        )
    if args.require_trigger_flag:
        names = trigger_flag_compatible_names(
            names,
            trigger_configs=trigger_configs,
            required_flags=args.require_trigger_flag,
        )
    selected = names[args.offset:]
    if args.limit is not None:
        selected = selected[:args.limit]
    payload = "".join(f"{name}\n" for name in selected)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(payload, encoding="utf-8")
    if args.manifest_out is not None:
        args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
        args.manifest_out.write_text(json.dumps({
            "test_reachable_diagnostic_types": len(test_reachable),
            "strictly_covered_diagnostic_types": len(
                strict_audit["verified_diagnostic_names"],
            ),
            "test_reachable_uncovered_diagnostic_types": len(strict_gap_names),
            "eligible_after_inflight_exclusion": len(all_gap_names),
            "inflight_diagnostic_types_excluded": len(excluded_names),
            "catalog_error_filter": str(args.catalog_dir)
            if args.catalog_dir is not None else None,
            "mode_compatible_diagnostic_types": len(names),
            "compile_mode": {
                "language": args.language,
                "cpp_standard": args.cpp_standard
                if args.language in {"c++", "objective-c++"} else None,
                "c_standard": args.c_standard
                if args.language in {"c", "objective-c"} else None,
                "feature_mode": args.feature_mode if args.language else None,
                "feature_specific_only": args.feature_specific_only,
                "plain_test_trigger": {
                    "language": args.plain_driver_language,
                    "standard": args.plain_driver_standard,
                } if args.plain_driver_language else None,
                "standard_only_test_trigger": {
                    "language": args.standard_trigger_language,
                    "standard": args.standard_trigger_standard,
                } if args.standard_trigger_language else None,
                "bare_language_test_trigger": args.bare_driver_language,
                "required_test_trigger_flags": args.require_trigger_flag,
            },
            "offset": args.offset,
            "limit": args.limit,
            "selected_diagnostic_types": len(selected),
            "diagnostic_names_sha256": hashlib.sha256(
                payload.encode("utf-8"),
            ).hexdigest(),
            "evidence_only": True,
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "test_reachable_uncovered_diagnostic_types": len(strict_gap_names),
        "eligible_after_inflight_exclusion": len(all_gap_names),
        "mode_compatible_diagnostic_types": len(names),
        "selected_diagnostic_types": len(selected),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
