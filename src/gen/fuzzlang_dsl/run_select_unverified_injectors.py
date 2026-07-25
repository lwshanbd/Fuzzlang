"""Select portable Injectors whose target lacks a strict-audit witness.

This lets replay prioritize already distilled, target-specific Injectors before
asking a model to synthesize another candidate for the same diagnostic.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def select_unverified_injectors(
    audit_path: Path,
    *,
    language: str,
    max_per_diagnostic: int,
) -> list[dict]:
    """Return bounded portable Injectors for targets absent from the audit."""
    audit = json.loads(audit_path.read_text())
    verified = set(audit["verified_diagnostic_names"])
    selected: list[dict] = []
    selected_ids: set[str] = set()
    selected_per_target: Counter[str] = Counter()

    for path_text in audit["inputs"]["injector_files"]:
        path = Path(path_text)
        if not path.is_file():
            continue
        for line in path.read_text().splitlines():
            row = json.loads(line)
            target = row.get("target", {}).get("diag_name")
            injector_id = row.get("injector_id")
            if (
                row.get("language") != language
                or not row.get("portable")
                or not isinstance(target, str)
                or target in verified
                or not isinstance(injector_id, str)
                or injector_id in selected_ids
                or selected_per_target[target] >= max_per_diagnostic
            ):
                continue
            selected.append(row)
            selected_ids.add(injector_id)
            selected_per_target[target] += 1
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--language", choices=("c", "c++"), required=True)
    parser.add_argument("--max-per-diagnostic", type=int, default=2)
    args = parser.parse_args()
    if args.max_per_diagnostic <= 0:
        parser.error("--max-per-diagnostic must be positive")

    selected = select_unverified_injectors(
        args.audit,
        language=args.language,
        max_per_diagnostic=args.max_per_diagnostic,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        for row in selected
    ))
    targets = {row["target"]["diag_name"] for row in selected}
    print(json.dumps({
        "injectors": len(selected),
        "target_diagnostics": len(targets),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
