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
        "min_tokens": 5,
        "median_tokens": 14.5,
        "max_tokens": 24,
    }
