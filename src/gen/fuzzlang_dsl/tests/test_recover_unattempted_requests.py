from __future__ import annotations

from gen.fuzzlang_dsl.run_recover_unattempted_requests import (
    select_unattempted_requests,
)


def test_recovery_keeps_only_request_rows_not_started_before_a_job_timeout():
    requests = [
        {"diag_name": "err_first"},
        {"diag_name": "err_second"},
        {"diag_name": "err_third"},
    ]
    attempts = [
        {"request_index": 0, "diag_name": "err_first", "status": "rejected"},
        {"request_index": 1, "diag_name": "err_second", "status": "exact_target"},
    ]

    assert select_unattempted_requests(requests, attempts) == [
        {"diag_name": "err_third"},
    ]


def test_recovery_uses_diagnostic_name_for_legacy_attempt_logs_without_indices():
    requests = [
        {"diag_name": "err_first"},
        {"diag_name": "err_second"},
    ]

    assert select_unattempted_requests(
        requests,
        [{"diag_name": "err_second", "status": "rejected"}],
    ) == [{"diag_name": "err_first"}]
