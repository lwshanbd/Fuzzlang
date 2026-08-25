import json

import pytest

from repair import run_sft


def _canonical_row() -> dict:
    return {
        "record_id": "r1",
        "erroneous_src": "int main() { return missing; }",
        "corrected_src": "int main() { return 0; }",
        "diagnostics": [
            {
                "diag_id": 123,
                "diag_name": "err_undeclared_var_use",
                "diag_msg": "use of undeclared identifier 'missing'",
                "file": "main.cc",
                "line": 1,
                "col": 21,
                "start_byte": 20,
                "end_byte": 27,
                "span_snippet": "missing",
            }
        ],
        "provenance": {
            "origin": "mutate",
            "source": "project:main.cc",
            "detail": {},
        },
        "split": "train",
        "language": "c++",
    }


def test_normalize_example_preserves_legacy_rows() -> None:
    row = {"source": "bad", "error": "compiler error", "fix": "good"}

    assert run_sft._normalize_example(row) == row


def test_normalize_example_converts_canonical_record() -> None:
    example = run_sft._normalize_example(_canonical_row())

    assert example["source"] == "int main() { return missing; }"
    assert example["fix"] == "int main() { return 0; }"
    assert example["record_id"] == "r1"
    assert example["error"] == (
        "err_undeclared_var_use [DiagID: 123]: use of undeclared identifier "
        "'missing' (main.cc:1:21)"
    )


def test_normalize_example_rejects_unpaired_canonical_record() -> None:
    row = _canonical_row()
    row["corrected_src"] = None
    row["split"] = "auxiliary"

    with pytest.raises(ValueError, match="corrected_src"):
        run_sft._normalize_example(row)


def test_native_chat_format_uses_tokenizer_template_without_system_role() -> None:
    calls = []

    class FakeTokenizer:
        chat_template = "available"

        def apply_chat_template(self, messages, **kwargs):
            calls.append((messages, kwargs))
            return "gemma-native-text"

    example = {"source": "bad", "error": "oops", "fix": "good"}

    rendered = run_sft._format_example(
        example, tokenizer=FakeTokenizer(), chat_template="native"
    )

    assert rendered == "gemma-native-text"
    messages, kwargs = calls[0]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert "bad" in messages[0]["content"]
    assert "oops" in messages[0]["content"]
    assert messages[1] == {"role": "assistant", "content": "good"}
    assert kwargs == {"tokenize": False, "add_generation_prompt": False}


def test_relative_edit_chat_format_requests_structured_window_offsets() -> None:
    row = {
        "source": "int x = missing;\n",
        "error": "undeclared identifier",
        "fix": '{"end_char":15,"replacement":"0","start_char":8}',
    }

    rendered = run_sft._format_example(row, target_format="relative-edit")

    assert "relative to the source window" in rendered
    assert "start_char" in rendered
    assert rendered.endswith(f"assistant\n{row['fix']}")


def test_legacy_chat_format_remains_the_default() -> None:
    row = {"source": "bad", "error": "oops", "fix": "good"}

    rendered = run_sft._format_example(row)

    assert rendered.startswith("system\nYou are an expert C/C++ programmer.")
    assert rendered.endswith("assistant\ngood")


def test_training_row_masks_prompt_and_preserves_native_template_suffix() -> None:
    class FakeTokenizer:
        chat_template = "available"

        def apply_chat_template(self, messages, **kwargs):
            assert kwargs == {"tokenize": False, "add_generation_prompt": False}
            return f"<user>{messages[0]['content']}<assistant>{messages[1]['content']}<eot>"

    row = {"source": "bad", "error": "oops", "fix": "good"}

    training_row = run_sft._make_prompt_completion(
        row, tokenizer=FakeTokenizer(), chat_template="native"
    )

    assert training_row["prompt"].endswith("<assistant>")
    assert training_row["completion"] == "good<eot>"
    assert training_row["prompt"] + training_row["completion"] == (
        run_sft._format_example(
            row, tokenizer=FakeTokenizer(), chat_template="native"
        )
    )


def test_training_config_uses_current_trl_names_and_optional_fsdp() -> None:
    args = run_sft._parse_args(
        [
            "--base-model", "gemma",
            "--data-path", "records.jsonl",
            "--adapter-out", "adapter",
            "--bf16",
            "--max-steps", "1",
            "--fsdp",
        ]
    )

    kwargs = run_sft._sft_config_kwargs(args)

    assert kwargs["max_length"] == 4096
    assert kwargs["max_steps"] == 1
    assert kwargs["model_init_kwargs"] == {
        "dtype": "bfloat16",
        "device_map": None,
        "local_files_only": False,
        "attn_implementation": "sdpa",
    }
    assert kwargs["gradient_checkpointing"] is False
    assert kwargs["fsdp"] is True
    assert kwargs["fsdp_config"]["version"] == 2
    assert kwargs["fsdp_config"]["reshard_after_forward"] is True
    assert kwargs["fsdp_config"]["auto_wrap_policy"] == "TRANSFORMER_BASED_WRAP"
    assert kwargs["fsdp_config"]["transformer_layer_cls_to_wrap"] == (
        "Gemma4TextDecoderLayer"
    )


def test_training_config_can_disable_gradient_checkpointing() -> None:
    args = run_sft._parse_args(
        [
            "--base-model", "gemma",
            "--data-path", "records.jsonl",
            "--adapter-out", "adapter",
            "--no-gradient-checkpointing",
        ]
    )

    kwargs = run_sft._sft_config_kwargs(args)

    assert kwargs["gradient_checkpointing"] is False


def test_lora_targets_only_gemma_language_model_layers() -> None:
    pattern = run_sft._LORA_TARGET_MODULES

    assert __import__("re").fullmatch(
        pattern, "model.language_model.layers.0.self_attn.q_proj"
    )
    assert __import__("re").fullmatch(
        pattern, "model.language_model.layers.59.mlp.down_proj"
    )
    assert not __import__("re").fullmatch(
        pattern, "model.vision_tower.vision_model.encoder.layers.0.self_attn.q_proj"
    )


def test_write_run_manifest_archives_data_and_adapter_hashes(tmp_path) -> None:
    data = tmp_path / "train.jsonl"
    data.write_text('{"record_id":"r1"}\n')
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "adapter_model.safetensors").write_bytes(b"adapter")
    args = run_sft._parse_args(
        [
            "--base-model", "gemma",
            "--model-revision", "abc123",
            "--data-path", str(data),
            "--adapter-out", str(adapter),
            "--target-format", "relative-edit",
            "--seed", "7",
            "--no-gradient-checkpointing",
        ]
    )

    path = run_sft._write_run_manifest(
        args,
        n_train=1,
        token_report={"total": 1, "kept": 1, "overlong": 0},
        train_metrics={"train_loss": 1.25},
        trainable_parameters=99,
    )

    manifest = json.loads(path.read_text())
    assert manifest["base_model"] == "gemma"
    assert manifest["model_revision"] == "abc123"
    assert manifest["n_train"] == 1
    assert manifest["seed"] == 7
    assert manifest["target_format"] == "relative-edit"
    assert manifest["gradient_checkpointing"] is False
    assert manifest["attn_implementation"] == "sdpa"
    assert manifest["train_metrics"] == {"train_loss": 1.25}
    assert manifest["trainable_parameters"] == 99
    assert len(manifest["data_sha256"]) == 64
    assert len(manifest["adapter_sha256"]) == 64


@pytest.mark.parametrize("size", [32, 128])
def test_prepare_smoke_examples_is_bounded_and_model_neutral(tmp_path, size) -> None:
    path = tmp_path / "records.jsonl"
    path.write_text(
        "".join(json.dumps(_canonical_row() | {"record_id": f"r{i}"}) + "\n" for i in range(140))
    )

    examples = run_sft._load_examples(path, limit=size)

    assert len(examples) == size
    assert set(examples[0]) == {"source", "error", "fix", "record_id"}


def test_load_examples_can_opt_in_to_localized_relative_edit(tmp_path) -> None:
    path = tmp_path / "records.jsonl"
    row = _canonical_row()
    row["erroneous_src"] = "before\nint x = missing;\nafter\n"
    row["corrected_src"] = "before\nint x = 0;\nafter\n"
    path.write_text(json.dumps(row) + "\n")

    examples = run_sft._load_examples(
        path,
        target_format="relative-edit",
        context_lines=0,
        max_window_chars=100,
        max_edit_chars=100,
    )

    assert examples == [
        {
            "source": "int x = missing;\n",
            "error": (
                "err_undeclared_var_use [DiagID: 123]: use of undeclared "
                "identifier 'missing' (main.cc:1:21)"
            ),
            "fix": '{"end_char":15,"replacement":"0","start_char":8}',
            "record_id": "r1",
        }
    ]


def test_load_examples_can_train_on_corrected_window_rewrite(tmp_path) -> None:
    path = tmp_path / "records.jsonl"
    row = _canonical_row()
    row["erroneous_src"] = "before\nint x = missing;\nafter\n"
    row["corrected_src"] = "before\nint x = 0;\nafter\n"
    path.write_text(json.dumps(row) + "\n")

    examples = run_sft._load_examples(
        path,
        target_format="window-rewrite",
        context_lines=0,
        max_window_chars=100,
        max_edit_chars=100,
    )

    assert examples[0]["source"] == "int x = missing;\n"
    assert json.loads(examples[0]["fix"]) == {
        "corrected_window": "int x = 0;\n"
    }


def test_window_rewrite_prompt_requests_one_corrected_window_object() -> None:
    row = {
        "source": "int x = missing;\n",
        "error": "undeclared identifier",
        "fix": '{"corrected_window":"int x = 0;\\n"}',
    }

    rendered = run_sft._format_example(row, target_format="window-rewrite")

    assert "corrected_window" in rendered
    assert "complete corrected source window" in rendered
    assert rendered.endswith(f"assistant\n{row['fix']}")


def test_dry_run_prepares_32_examples_without_training_imports(tmp_path) -> None:
    source = tmp_path / "records.jsonl"
    prepared = tmp_path / "prepared.jsonl"
    source.write_text(
        "".join(json.dumps(_canonical_row() | {"record_id": f"r{i}"}) + "\n" for i in range(40))
    )

    result = run_sft.main(
        [
            "--data-path",
            str(source),
            "--smoke-size",
            "32",
            "--dry-run",
            "--prepared-out",
            str(prepared),
        ]
    )

    assert result == 0
    assert len(prepared.read_text().splitlines()) == 32


def test_token_length_preflight_rejects_silent_truncation() -> None:
    class LengthTokenizer:
        def __call__(self, text, **kwargs):
            return {"input_ids": list(range(len(text)))}

    rendered = ["short", "this example is too long"]

    with pytest.raises(ValueError, match="1/2.*max_seq_len=10"):
        run_sft._preflight_token_lengths(
            rendered, LengthTokenizer(), max_seq_len=10, overlong="error"
        )


def test_token_length_preflight_drops_only_with_explicit_opt_in() -> None:
    class LengthTokenizer:
        def __call__(self, text, **kwargs):
            return {"input_ids": list(range(len(text)))}

    kept, report = run_sft._preflight_token_lengths(
        ["short", "this example is too long"],
        LengthTokenizer(),
        max_seq_len=10,
        overlong="drop",
    )

    assert kept == ["short"]
    assert report == {
        "total": 2,
        "kept": 1,
        "overlong": 1,
        "total_tokens": 29,
        "min_tokens": 5,
        "median_tokens": 14.5,
        "max_tokens": 24,
    }


def test_only_the_main_process_writes_the_run_manifest(monkeypatch):
    # Under torchrun every rank runs main(). If each writes the manifest, the
    # non-zero ranks race rank 0's adapter save and abort a training run that
    # actually succeeded -- which is what happened to the 31B run after all
    # 3,000 steps had completed.
    from repair import run_sft

    monkeypatch.setenv("RANK", "2")
    assert run_sft.is_main_process() is False

    monkeypatch.setenv("RANK", "0")
    assert run_sft.is_main_process() is True

    monkeypatch.delenv("RANK", raising=False)
    monkeypatch.delenv("LOCAL_RANK", raising=False)
    assert run_sft.is_main_process() is True


def test_diagnostic_detail_levels_control_what_the_prompt_reveals():
    # The prompt hands the model the diagnostic name, its message, and the exact
    # file:line:col. A reviewer will ask how much of the repair rate is the
    # model and how much is being told where to look, so the prompt has to be
    # able to withhold each part.
    from repair.run_sft import _messages_for_example

    row = {
        "source": "int x = y;",
        "error": "err_undeclared_var_use [DiagID: 12]: use of undeclared "
                 "identifier 'y' (src/a.cpp:1:9)",
        "fix": '{"corrected_window": "int x = 0;"}',
    }

    full = _messages_for_example(row, target_format="window-rewrite")[0]["content"]
    assert "err_undeclared_var_use" in full and "src/a.cpp:1:9" in full

    no_loc = _messages_for_example(
        row, target_format="window-rewrite", diagnostic_detail="no-location",
    )[0]["content"]
    assert "err_undeclared_var_use" in no_loc
    assert "src/a.cpp:1:9" not in no_loc

    none = _messages_for_example(
        row, target_format="window-rewrite", diagnostic_detail="none",
    )[0]["content"]
    assert "err_undeclared_var_use" not in none
    assert "Compiler diagnostic" not in none
    # The task still has to be stated, or the model is being asked nothing.
    assert "int x = y;" in none


def test_the_default_prompt_is_unchanged_so_training_is_not_affected():
    from repair.run_sft import _messages_for_example

    row = {"source": "s", "error": "e (a.cpp:1:1)", "fix": "f"}
    assert (
        _messages_for_example(row, target_format="window-rewrite")
        == _messages_for_example(
            row, target_format="window-rewrite", diagnostic_detail="full")
    )


def test_an_unknown_detail_level_is_rejected():
    import pytest as _pytest
    from repair.run_sft import _messages_for_example

    with _pytest.raises(ValueError):
        _messages_for_example(
            {"source": "s", "error": "e", "fix": "f"},
            target_format="window-rewrite", diagnostic_detail="nonsense",
        )
