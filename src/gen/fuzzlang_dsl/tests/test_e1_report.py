from __future__ import annotations

from gen.fuzzlang_dsl.e1_report import (
    build_e1_report, failure_mode_counts, new_strict_coverage,
    replay_arm_summary,
)


def _attempt(**kwargs) -> dict:
    row = {
        "arm": "direct_edit", "target": "err_a", "stage": "model",
        "source_id": "llvm:a.cpp", "project": "llvm", "candidate_index": 0,
        "status": "rejected", "reason": None, "observed_diag": None,
        "observed_diag_id": None, "output_tokens": 0, "injector_id": None,
        "response_text": None, "compile_cmd": [],
    }
    row.update(kwargs)
    return row


def _comparison() -> dict:
    return {
        "arms": [
            {
                "arm": "direct_edit", "targets": 2,
                "targets_with_accepted_record": 1, "target_hit_rate": 0.5,
                "accepted_records": 3, "accepted_injectors": 0,
                "wall_seconds": 100.0,
                "budget": {
                    "model_calls": 12, "prompt_tokens": 0,
                    "output_tokens": 6000, "model_seconds": 3600.0,
                    "compiler_invocations": 24, "compiler_seconds": 0.0,
                },
                "efficiency": {
                    "records_per_1k_output_tokens": 0.5,
                    "records_per_gpu_hour": 3.0,
                    "output_tokens_per_accepted_record": 2000.0,
                    "compiler_invocations_per_accepted_record": 8.0,
                    "model_calls_per_accepted_record": 4.0,
                },
            },
            {
                "arm": "injector", "targets": 2,
                "targets_with_accepted_record": 2, "target_hit_rate": 1.0,
                "accepted_records": 6, "accepted_injectors": 3,
                "wall_seconds": 50.0,
                "budget": {
                    "model_calls": 2, "prompt_tokens": 0,
                    "output_tokens": 3000, "model_seconds": 1800.0,
                    "compiler_invocations": 20, "compiler_seconds": 0.0,
                },
                "efficiency": {
                    "records_per_1k_output_tokens": 2.0,
                    "records_per_gpu_hour": 12.0,
                    "output_tokens_per_accepted_record": 500.0,
                    "compiler_invocations_per_accepted_record": 3.3333,
                    "model_calls_per_accepted_record": 0.3333,
                },
            },
        ],
        "per_target": {
            "err_a": {
                "direct_edit": {
                    "attempted_sources": 6, "accepted_records": 3,
                    "exact_target_rate_per_source": 0.5, "transfer_sources": 1,
                    "available_transfer_sources": 2, "transfer_rate": 0.5,
                    "replay_sources": 3, "accepted_injectors": 0, "held_out_source_rate": 0.5,
                    "replaying_injectors": 0, "model_calls": 6,
                    "primary_project": "llvm",
                },
                "injector": {
                    "attempted_sources": 6, "accepted_records": 4,
                    "exact_target_rate_per_source": 0.6667, "transfer_sources": 2,
                    "available_transfer_sources": 2, "transfer_rate": 1.0,
                    "replay_sources": 4, "accepted_injectors": 2, "held_out_source_rate": 1.0,
                    "replaying_injectors": 1, "model_calls": 1,
                    "primary_project": "llvm",
                },
            },
            "err_b": {
                "direct_edit": {
                    "attempted_sources": 6, "accepted_records": 0,
                    "exact_target_rate_per_source": 0.0, "transfer_sources": 0,
                    "available_transfer_sources": 2, "transfer_rate": 0.0,
                    "replay_sources": 0, "accepted_injectors": 0, "held_out_source_rate": 0.0,
                    "replaying_injectors": 0, "model_calls": 6,
                    "primary_project": "llvm",
                },
                "injector": {
                    "attempted_sources": 6, "accepted_records": 2,
                    "exact_target_rate_per_source": 0.3333, "transfer_sources": 0,
                    "available_transfer_sources": 2, "transfer_rate": 0.0,
                    "replay_sources": 2, "accepted_injectors": 1, "held_out_source_rate": 0.25,
                    "replaying_injectors": 1, "model_calls": 1,
                    "primary_project": "llvm",
                },
            },
        },
    }


def test_failure_modes_are_counted_per_arm_and_ranked():
    attempts = [
        _attempt(reason="wrong_primary_diagnostic", observed_diag="err_x"),
        _attempt(reason="wrong_primary_diagnostic", observed_diag="err_y"),
        _attempt(reason="mutant_compiles_clean"),
        _attempt(arm="injector", reason="injector_does_not_match_source"),
        _attempt(status="accepted", reason=None),
    ]

    counts = failure_mode_counts(attempts)

    assert counts["direct_edit"] == {
        "wrong_primary_diagnostic": 2, "mutant_compiles_clean": 1,
    }
    assert counts["injector"] == {"injector_does_not_match_source": 1}


def test_new_strict_coverage_counts_only_diagnostics_absent_from_the_audit():
    per_target = {
        "err_new": {"injector": {"accepted_records": 2}},
        "err_known": {"injector": {"accepted_records": 1}},
        "err_none": {"injector": {"accepted_records": 0}},
    }

    result = new_strict_coverage(
        per_target, arm="injector", covered={"err_known"},
    )

    assert result == {"covered_types": 2, "new_types": 1, "new_names": ["err_new"]}


def test_report_builds_the_comparable_arm_table_with_bootstrap_intervals():
    report = build_e1_report(
        _comparison(), attempts=[], covered=set(), bootstrap_samples=200, seed=1,
    )

    table = {row["arm"]: row for row in report["table"]}
    assert table["injector"]["accepted_records"] == 6
    assert table["direct_edit"]["accepted_records"] == 3
    assert table["injector"]["records_per_1k_output_tokens"] == 2.0
    assert table["injector"]["model_calls"] == 2
    # Per-diagnostic exact-target rate is a macro average over the sample.
    assert table["direct_edit"]["macro_exact_target_rate"] == 0.25
    assert table["injector"]["macro_exact_target_rate"] == 0.5
    interval = table["injector"]["macro_exact_target_rate_ci95"]
    assert interval[0] <= 0.5 <= interval[1]
    assert table["injector"]["macro_held_out_source_rate"] == 0.625
    assert table["direct_edit"]["macro_held_out_source_rate"] == 0.25


def test_report_flags_a_sample_too_small_for_a_conclusion():
    report = build_e1_report(
        _comparison(), attempts=[], covered=set(), bootstrap_samples=200, seed=1,
    )

    assert report["sample"]["targets"] == 2
    assert report["sample"]["sufficient_for_conclusion"] is False
    assert "smoke" in report["sample"]["interpretation"].lower()


def _replay_record(record_id, *, injector, diag, project, path):
    return {
        "record_id": record_id,
        "provenance": {"detail": {
            "injector_id": injector, "target_diag": diag,
            "project": project, "source_path": path,
        }},
    }


def test_replay_summary_counts_reach_from_the_records_themselves():
    # injector_reach.json stores only counts, so a filtered recount has to come
    # from the records; this checks the recount reproduces the same shape.
    records = [
        _replay_record("r0", injector="i0", diag="err_a", project="p", path="a.cc"),
        _replay_record("r1", injector="i0", diag="err_b", project="q", path="b.cc"),
        _replay_record("r2", injector="i1", diag="err_a", project="p", path="a.cc"),
    ]

    summary = replay_arm_summary(records)

    assert summary["records"] == 3
    assert summary["diagnostics"] == 2
    assert summary["projects"] == 2
    assert summary["source_tus"] == 2
    assert summary["injectors_with_a_record"] == 2
    assert summary["sources_per_injector_mean"] == 1.5
    assert summary["injectors_reaching_multiple_sources"] == 1
    assert summary["injectors_reaching_multiple_projects"] == 1
    assert summary["per_project_records"]["p"] == {
        "records": 2, "diagnostics": 1, "source_tus": 1,
    }


def test_replay_summary_can_drop_vendored_dependency_sources():
    # duckdb and protobuf fetch Abseil into build/_deps; source under such a
    # path is not the project it is attributed to, so it must be excludable.
    records = [
        _replay_record("r0", injector="i0", diag="err_a", project="duckdb",
                       path="duckdb/src/main.cpp"),
        _replay_record("r1", injector="i0", diag="err_b", project="duckdb",
                       path="duckdb/build/_deps/absl-src/absl/base/log.cc"),
    ]

    kept = replay_arm_summary(records, exclude_vendored=True)

    assert kept["records"] == 1
    assert kept["diagnostics"] == 1
    assert kept["excluded_vendored"] == 1
    assert replay_arm_summary(records)["records"] == 2
