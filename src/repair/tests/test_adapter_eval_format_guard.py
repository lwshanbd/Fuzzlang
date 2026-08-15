from __future__ import annotations

import json

import pytest

from repair.run_adapter_eval import adapter_training_target_format, check_target_format


def _manifest(tmp_path, target_format: str):
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "run-manifest.json").write_text(
        json.dumps({"target_format": target_format})
    )
    return adapter


def test_the_adapter_training_format_is_read_from_its_run_manifest(tmp_path):
    adapter = _manifest(tmp_path, "window-rewrite")

    assert adapter_training_target_format(adapter) == "window-rewrite"
    assert adapter_training_target_format(None) is None
    assert adapter_training_target_format(tmp_path / "missing") is None


def test_evaluating_an_adapter_in_the_wrong_representation_is_refused(tmp_path):
    """A silent train/eval representation mismatch scores a model on a task it
    was never taught, and it looks like a real (terrible) result rather than a
    configuration error."""
    adapter = _manifest(tmp_path, "window-rewrite")

    with pytest.raises(ValueError, match="window-rewrite"):
        check_target_format(adapter, requested="relative-edit")

    check_target_format(adapter, requested="window-rewrite")
    check_target_format(None, requested="relative-edit")


def test_an_explicit_override_allows_a_deliberate_cross_format_probe(tmp_path):
    adapter = _manifest(tmp_path, "window-rewrite")

    check_target_format(adapter, requested="relative-edit", allow_mismatch=True)
