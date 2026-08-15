from gen.fuzzlang_dsl.checkpoint_summary import summarize_checkpoint_campaign


def test_checkpoint_summary_counts_durable_candidate_outcomes_and_records():
    metrics = summarize_checkpoint_campaign(
        [{"injector_id": "i", "target": {"diag_name": "err_target"}}],
        [{"injector_id": "i", "status": "near_miss"}],
        [{"provenance": {"detail": {"injector_id": "i"}}}],
    )

    assert metrics == [{
        "injector_id": "i", "target_diag": "err_target", "compiled": 2,
        "exact_target": 1, "records_emitted": 1,
    }]
