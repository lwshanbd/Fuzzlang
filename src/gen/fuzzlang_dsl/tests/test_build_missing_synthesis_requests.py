from __future__ import annotations

import json

from gen.fuzzlang_dsl.build_missing_synthesis_requests import missing_requests


def test_missing_requests_deduplicates_and_excludes_covered_targets(tmp_path):
    requests, injectors = tmp_path / "requests.jsonl", tmp_path / "injectors.jsonl"
    requests.write_text("".join(json.dumps({"diag_name": name}) + "\n" for name in ("err_a", "err_b", "err_b")))
    injectors.write_text(json.dumps({"target": {"diag_name": "err_a"}}) + "\n")
    assert missing_requests(requests, [injectors]) == [{"diag_name": "err_b"}]
