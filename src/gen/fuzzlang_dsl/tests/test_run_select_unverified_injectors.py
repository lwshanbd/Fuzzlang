from __future__ import annotations

import json

from gen.fuzzlang_dsl.run_select_unverified_injectors import (
    select_unverified_injectors,
)


def test_selects_only_portable_unverified_language_matched_injectors(tmp_path):
    injectors = tmp_path / "injectors.jsonl"
    rows = [
        {"injector_id": "covered", "language": "c++", "portable": True,
         "target": {"diag_name": "err_covered"}},
        {"injector_id": "first", "language": "c++", "portable": True,
         "target": {"diag_name": "err_gap"}},
        {"injector_id": "second", "language": "c++", "portable": True,
         "target": {"diag_name": "err_gap"}},
        {"injector_id": "third", "language": "c++", "portable": True,
         "target": {"diag_name": "err_gap"}},
        {"injector_id": "c", "language": "c", "portable": True,
         "target": {"diag_name": "err_c_gap"}},
        {"injector_id": "local", "language": "c++", "portable": False,
         "target": {"diag_name": "err_local"}},
    ]
    injectors.write_text("".join(json.dumps(row) + "\n" for row in rows))
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps({
        "verified_diagnostic_names": ["err_covered"],
        "inputs": {"injector_files": [str(injectors)]},
    }))

    selected = select_unverified_injectors(
        audit, language="c++", max_per_diagnostic=2,
    )

    assert [row["injector_id"] for row in selected] == ["first", "second"]
