"""Select auditable retry requests from a completed local synthesis batch."""
from __future__ import annotations

import copy
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


_RETRY_GUIDANCE = (
    "Retry validation feedback: a prior proposal was rejected. Use a contiguous "
    "sequence of exact lexer tokens that occurs in a supplied correct snippet; "
    "do not concatenate punctuation, identifiers, or <IDn> placeholders inside "
    "one match element. Represent non-keyword identifiers as <IDn>, and use the "
    "bare label (for example ID0) in a binding replacement."
)


def load_json_rows(path: str | Path) -> list[dict[str, Any]]:
    """Load a JSON object/list or JSONL file into strict object rows."""
    text = Path(path).read_text()
    if not text.strip():
        return []
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        values = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        values = value if isinstance(value, list) else [value]
    if any(not isinstance(value, dict) for value in values):
        raise ValueError("every row must be a JSON object")
    return values


def select_retry_requests(
    requests: Sequence[Mapping[str, Any]],
    attempts: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Keep only attempted targets with no accepted candidate.

    The returned rows retain compiler evidence and source snippets.  A concise
    validation note is appended to the evidence so the next local run learns
    from structural, not semantic, rejection feedback.
    """
    request_names: set[str] = set()
    ordered_requests: list[Mapping[str, Any]] = []
    for request in requests:
        name = request.get("diag_name")
        if not isinstance(name, str) or not name:
            raise ValueError("each request requires a non-empty diag_name")
        if name in request_names:
            raise ValueError(f"duplicate request diag_name: {name}")
        request_names.add(name)
        ordered_requests.append(request)

    statuses: dict[str, set[str]] = defaultdict(set)
    reasons: dict[str, set[str]] = defaultdict(set)
    for attempt in attempts:
        name = attempt.get("diag_name")
        status = attempt.get("status")
        if not isinstance(name, str) or name not in request_names:
            continue
        if not isinstance(status, str):
            raise ValueError(f"attempt for {name} has no string status")
        statuses[name].add(status)
        reason = attempt.get("reason")
        if isinstance(reason, str) and reason:
            reasons[name].add(reason)

    selected: list[dict[str, Any]] = []
    for request in ordered_requests:
        name = request["diag_name"]
        if name not in statuses or "accepted" in statuses[name]:
            continue
        row = copy.deepcopy(dict(request))
        evidence = row.get("emission_evidence")
        if evidence is not None and not isinstance(evidence, str):
            raise ValueError(f"request {name} has non-string emission_evidence")
        feedback = _RETRY_GUIDANCE
        if reasons[name]:
            feedback += " Previous rejection labels: " + ", ".join(sorted(reasons[name])) + "."
        row["emission_evidence"] = (
            (evidence.rstrip() + "\n\n") if evidence else ""
        ) + feedback
        selected.append(row)

    summary = {
        "requests": len(ordered_requests),
        "attempted_targets": len(statuses),
        "accepted_targets": sum("accepted" in value for value in statuses.values()),
        "retry_targets": len(selected),
        "unattempted_targets": len(ordered_requests) - len(statuses),
    }
    return selected, summary
