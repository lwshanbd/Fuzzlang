#!/usr/bin/env python3
"""B2 LoRA SFT driver for Qwen2.5-Coder-7B on Fuzzlang-LLVM (buggy, error, fixed) triples.

Called from scripts/polaris_qsub_sft.sh. Produces a LoRA adapter at
`--adapter-out` that the sweep driver loads (via vLLM --enable-lora) for the
B2 and B3 baselines.

Keep the recipe aligned with Fuzzlang v1 for baseline equivalence: rank 16,
alpha 32, 1 epoch, bs 8, lr 2e-4, bf16, no warmup, AdamW.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


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


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--base-model", required=True, help="Qwen2.5-Coder-7B HF repo path.")
    p.add_argument("--data-path", required=True, help="JSONL with {source, error, fix}.")
    p.add_argument("--adapter-out", required=True)
    p.add_argument("--lora-rank", type=int, default=16)
    p.add_argument("--lora-alpha", type=int, default=32)
    p.add_argument("--epochs", type=int, default=1)
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--grad-accum", type=int, default=4)
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--bf16", action="store_true")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--max-seq-len", type=int, default=4096)
    p.add_argument("--limit", type=int, default=None,
                   help="Cap training set size for smoke/debug.")
    return p.parse_args()


def _format_example(row: dict) -> str:
    return _FUZZLANG_CHAT_TEMPLATE.format(
        source=row["source"], error=row["error"], fix=row["fix"],
    )


def main() -> int:
    args = _parse_args()

    # Lazy heavy imports so --help is fast and unit tests don't bring them in.
    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        TrainingArguments,
    )
    from trl import SFTTrainer

    print(f"[run_sft] base={args.base_model} out={args.adapter_out}", flush=True)

    # Load data.
    rows: list[dict] = []
    with Path(args.data_path).open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
            if args.limit is not None and len(rows) >= args.limit:
                break
    print(f"[run_sft] n_train={len(rows)}", flush=True)
    ds = Dataset.from_list([{"text": _format_example(r)} for r in rows])

    # Model + tokenizer.
    tok = AutoTokenizer.from_pretrained(args.base_model)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    dtype = torch.bfloat16 if args.bf16 else torch.float16
    model = AutoModelForCausalLM.from_pretrained(
        args.base_model, torch_dtype=dtype, device_map="auto",
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
