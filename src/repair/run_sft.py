#!/usr/bin/env python3
"""Model-neutral LoRA SFT driver for FuzzLang diagnostic-repair pairs.

The driver accepts both canonical :class:`foundation.record.Record` JSONL and
the legacy ``{source, error, fix}`` triples.  The legacy hand-written prompt is
kept for baseline reproducibility; ``--chat-template native`` uses the base
model tokenizer's own template and is the intended path for Gemma.

``--dry-run`` deliberately stops before loading the model or importing the SFT
training stack.  Together with ``--smoke-size {32,128}`` it provides a cheap,
offline validation and data-preparation path before requesting GPU resources.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Sequence

from repair.sft_data import format_diagnostic, make_localized_repair_example


_FUZZLANG_CHAT_TEMPLATE = (
    # Mirrors Fuzzlang v1 Fig. 8 fine-tuning prompt. Kept here so whatever
    # chat template the base model defaults to, the SFT set is consistent.
    "system\n"
    "You are an expert C/C++ programmer. Given the source and the compiler error, "
    "return the corrected code only.\n"
    "user\n"
    "Source:\n```\n{source}\n```\nError:\n{error}\n"
    "assistant\n"
    "{fix}"
)

_REPAIR_INSTRUCTION = (
    "You are an expert C/C++ programmer. Given the source and the compiler "
    "diagnostic, return the corrected code only."
)

_RELATIVE_EDIT_INSTRUCTION = (
    "You are an expert C/C++ programmer. Given an erroneous source window and "
    "the compiler diagnostic, return exactly one JSON object with start_char, "
    "end_char, and replacement. The half-open character offsets must be relative "
    "to the source window."
)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--base-model",
        help="Local path or Hugging Face identifier for any causal language model.",
    )
    p.add_argument(
        "--data-path",
        required=True,
        help="Canonical FuzzLang Record JSONL or legacy {source,error,fix} JSONL.",
    )
    p.add_argument("--adapter-out")
    p.add_argument("--lora-rank", type=int, default=16)
    p.add_argument("--lora-alpha", type=int, default=32)
    p.add_argument("--epochs", type=int, default=1)
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--grad-accum", type=int, default=4)
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--bf16", action="store_true")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--max-seq-len", type=int, default=4096)
    limit = p.add_mutually_exclusive_group()
    limit.add_argument(
        "--limit", type=int, default=None, help="Cap training set size."
    )
    limit.add_argument(
        "--smoke-size",
        type=int,
        choices=(32, 128),
        help="Use the deterministic first 32 or 128 records for a smoke run.",
    )
    p.add_argument(
        "--chat-template",
        choices=("legacy", "native"),
        default="legacy",
        help=(
            "Formatting policy. 'legacy' preserves the original FuzzLang prompt; "
            "'native' uses tokenizer.apply_chat_template (recommended for Gemma)."
        ),
    )
    p.add_argument(
        "--target-format",
        choices=("full-source", "relative-edit"),
        default="full-source",
        help=(
            "Train on the complete corrected source or an exactly replayable "
            "JSON edit relative to a bounded source window."
        ),
    )
    p.add_argument("--context-lines", type=int, default=8)
    p.add_argument("--max-window-chars", type=int, default=8_000)
    p.add_argument("--max-edit-chars", type=int, default=2_000)
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate/prepare data, print a summary, and do not load/train a model.",
    )
    p.add_argument(
        "--prepared-out",
        help="Optional path for normalized model-neutral {source,error,fix} JSONL.",
    )
    p.add_argument(
        "--local-files-only",
        action="store_true",
        help="Disallow model/tokenizer network access (recommended on compute nodes).",
    )
    p.add_argument(
        "--overlong",
        choices=("error", "drop", "truncate"),
        default="error",
        help=(
            "Policy for rendered examples longer than --max-seq-len. The safe "
            "default rejects them instead of silently truncating the repair."
        ),
    )
    return p.parse_args(argv)


def _normalize_example(
    row: dict[str, Any],
    *,
    target_format: str = "full-source",
    context_lines: int = 8,
    max_window_chars: int = 8_000,
    max_edit_chars: int = 2_000,
) -> dict[str, str]:
    """Convert a legacy triple or canonical Record mapping to one repair triple."""

    if target_format == "relative-edit":
        return make_localized_repair_example(
            row,
            context_lines=context_lines,
            max_window_chars=max_window_chars,
            max_edit_chars=max_edit_chars,
        ).to_training_example()
    if target_format != "full-source":
        raise ValueError(f"unknown target format: {target_format}")

    legacy_keys = ("source", "error", "fix")
    if all(key in row for key in legacy_keys):
        result = {key: str(row[key]) for key in legacy_keys}
        if "record_id" in row:
            result["record_id"] = str(row["record_id"])
        return result

    if "erroneous_src" not in row:
        raise ValueError(
            "row must be a canonical Record or contain source, error, and fix"
        )
    corrected = row.get("corrected_src")
    if not corrected:
        raise ValueError("canonical SFT row requires non-empty corrected_src")
    diagnostics = row.get("diagnostics")
    if not isinstance(diagnostics, list) or not diagnostics:
        raise ValueError("canonical SFT row requires at least one diagnostic")

    result = {
        "source": str(row["erroneous_src"]),
        "error": format_diagnostic(diagnostics[0]),
        "fix": str(corrected),
    }
    if "record_id" in row:
        result["record_id"] = str(row["record_id"])
    return result


def _load_examples(
    path: str | Path,
    limit: int | None = None,
    *,
    target_format: str = "full-source",
    context_lines: int = 8,
    max_window_chars: int = 8_000,
    max_edit_chars: int = 2_000,
) -> list[dict[str, str]]:
    """Load and normalize at most ``limit`` non-empty JSONL rows."""

    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")
    examples: list[dict[str, str]] = []
    with Path(path).open() as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                examples.append(
                    _normalize_example(
                        row,
                        target_format=target_format,
                        context_lines=context_lines,
                        max_window_chars=max_window_chars,
                        max_edit_chars=max_edit_chars,
                    )
                )
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid SFT row at {path}:{line_number}: {exc}") from exc
            if limit is not None and len(examples) >= limit:
                break
    if not examples:
        raise ValueError(f"no SFT examples found in {path}")
    return examples


def _messages_for_example(
    row: dict[str, str], *, target_format: str = "full-source"
) -> list[dict[str, str]]:
    """Build Gemma-compatible user/assistant messages (Gemma has no system turn)."""

    if target_format == "full-source":
        instruction = _REPAIR_INSTRUCTION
        source_label = "Source"
    elif target_format == "relative-edit":
        instruction = _RELATIVE_EDIT_INSTRUCTION
        source_label = "Source window"
    else:
        raise ValueError(f"unknown target format: {target_format}")
    user = (
        f"{instruction}\n\n"
        f"{source_label}:\n```\n{row['source']}\n```\n"
        f"Compiler diagnostic:\n{row['error']}"
    )
    return [
        {"role": "user", "content": user},
        {"role": "assistant", "content": row["fix"]},
    ]


def _format_example(
    row: dict[str, str],
    *,
    tokenizer: Any | None = None,
    chat_template: str = "legacy",
    target_format: str = "full-source",
) -> str:
    if chat_template == "legacy":
        if target_format == "relative-edit":
            return (
                f"system\n{_RELATIVE_EDIT_INSTRUCTION}\n"
                f"user\nSource window:\n```\n{row['source']}\n```\n"
                f"Error:\n{row['error']}\nassistant\n{row['fix']}"
            )
        if target_format != "full-source":
            raise ValueError(f"unknown target format: {target_format}")
        return _FUZZLANG_CHAT_TEMPLATE.format(
            source=row["source"], error=row["error"], fix=row["fix"],
        )
    if chat_template != "native":
        raise ValueError(f"unknown chat template policy: {chat_template}")
    if tokenizer is None or not callable(getattr(tokenizer, "apply_chat_template", None)):
        raise ValueError("native chat formatting requires a tokenizer chat template")
    if not getattr(tokenizer, "chat_template", None):
        raise ValueError("tokenizer does not define a native chat template")
    return tokenizer.apply_chat_template(
        _messages_for_example(row, target_format=target_format),
        tokenize=False,
        add_generation_prompt=False,
    )


def _write_prepared(path: str | Path, examples: Sequence[dict[str, str]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w") as f:
        for example in examples:
            f.write(json.dumps(example, sort_keys=True) + "\n")


def _preflight_token_lengths(
    rendered: Sequence[str],
    tokenizer: Any,
    *,
    max_seq_len: int,
    overlong: str = "error",
) -> tuple[list[str], dict[str, int | float]]:
    """Measure complete prompt+answer lengths before TRL can truncate them."""

    if max_seq_len <= 0:
        raise ValueError("max_seq_len must be positive")
    if overlong not in {"error", "drop", "truncate"}:
        raise ValueError(f"unknown overlong policy: {overlong}")
    lengths = [
        len(tokenizer(text, truncation=False)["input_ids"]) for text in rendered
    ]
    if not lengths:
        raise ValueError("cannot train on an empty rendered dataset")
    overlong_indices = [
        index for index, length in enumerate(lengths) if length > max_seq_len
    ]
    if overlong_indices and overlong == "error":
        raise ValueError(
            f"{len(overlong_indices)}/{len(rendered)} rendered examples exceed "
            f"max_seq_len={max_seq_len} (max={max(lengths)}); choose "
            "--overlong drop or --overlong truncate explicitly"
        )
    if overlong == "drop":
        overlong_set = set(overlong_indices)
        kept = [text for index, text in enumerate(rendered) if index not in overlong_set]
    else:
        kept = list(rendered)
    if not kept:
        raise ValueError("the overlong policy removed every training example")
    report: dict[str, int | float] = {
        "total": len(rendered),
        "kept": len(kept),
        "overlong": len(overlong_indices),
        "min_tokens": min(lengths),
        "median_tokens": statistics.median(lengths),
        "max_tokens": max(lengths),
    }
    return kept, report


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    limit = args.smoke_size if args.smoke_size is not None else args.limit
    rows = _load_examples(
        args.data_path,
        limit=limit,
        target_format=args.target_format,
        context_lines=args.context_lines,
        max_window_chars=args.max_window_chars,
        max_edit_chars=args.max_edit_chars,
    )
    if args.prepared_out:
        _write_prepared(args.prepared_out, rows)

    print(
        f"[run_sft] n_train={len(rows)} mode={'dry-run' if args.dry_run else 'train'} "
        f"format={args.chat_template} target={args.target_format}",
        flush=True,
    )
    if args.prepared_out:
        print(f"[run_sft] prepared={args.prepared_out}", flush=True)
    if args.dry_run and not args.base_model:
        print(
            "[run_sft] token_preflight=skipped (pass --base-model to enable)",
            flush=True,
        )
        return 0
    if not args.base_model:
        raise ValueError("--base-model is required for training")

    # A tokenizer-only dry run is useful on a login/CPU node and does not load
    # the model or import the training stack.
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(
        args.base_model, local_files_only=args.local_files_only
    )
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    rendered = [
        _format_example(
            row,
            tokenizer=tok,
            chat_template=args.chat_template,
            target_format=args.target_format,
        )
        for row in rows
    ]
    rendered, length_report = _preflight_token_lengths(
        rendered,
        tok,
        max_seq_len=args.max_seq_len,
        overlong=args.overlong,
    )
    print(
        "[run_sft] token_preflight "
        + " ".join(f"{key}={value}" for key, value in length_report.items()),
        flush=True,
    )
    if args.dry_run:
        return 0
    if not args.adapter_out:
        raise ValueError("--adapter-out is required for training")

    # Lazy heavy imports so --help and tokenizer-only dry runs avoid the model
    # and training dependencies.
    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, TrainingArguments
    from trl import SFTTrainer

    print(f"[run_sft] base={args.base_model} out={args.adapter_out}", flush=True)

    ds = Dataset.from_list([{"text": text} for text in rendered])
    dtype = torch.bfloat16 if args.bf16 else torch.float16
    model = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        torch_dtype=dtype,
        device_map="auto",
        local_files_only=args.local_files_only,
    )

    lora = LoraConfig(
        r=args.lora_rank, lora_alpha=args.lora_alpha, lora_dropout=0.05,
        bias="none", task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    targs = TrainingArguments(
        output_dir=args.adapter_out,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_ratio=0.0,
        bf16=args.bf16,
        fp16=not args.bf16,
        logging_steps=25,
        save_strategy="epoch",
        seed=args.seed,
        gradient_checkpointing=True,
        report_to=[],           # no wandb by default; enable externally if wanted.
    )

    trainer = SFTTrainer(
        model=model, tokenizer=tok,
        train_dataset=ds, args=targs,
        dataset_text_field="text", max_seq_length=args.max_seq_len,
    )
    trainer.train()
    trainer.save_model(args.adapter_out)
    print(f"[run_sft] adapter saved to {args.adapter_out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
