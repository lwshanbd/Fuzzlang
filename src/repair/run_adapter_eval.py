#!/usr/bin/env python3
"""Load a local base/LoRA model and compiler-verify localized repairs.

This is the inference-side gate paired with :mod:`repair.run_sft`.  It uses the
same native chat prompt and localized source-window representation, parses an
offset edit or corrected-window JSON object, reconstructs the complete
translation unit, and invokes the pinned FuzzLang Clang verifier. Results and
raw generations are archived as a summary JSON plus per-instance JSONL.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Sequence

from foundation.verifier import FuzzlangClangVerifier
from repair.run_sft import _messages_for_example
from repair.sft_data import (
    LocalizedRepairExample,
    RelativeEdit,
    apply_localized_repair,
    make_localized_repair_example,
)


def parse_relative_edit(text: str) -> RelativeEdit:
    """Extract one valid relative-edit object from a model response."""

    decoder = json.JSONDecoder()
    saw_object = False
    validation_errors: list[str] = []
    for start, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        saw_object = True
        if set(value) != {"start_char", "end_char", "replacement"}:
            validation_errors.append(
                "relative edit must contain exactly start_char, end_char, and replacement"
            )
            continue
        if type(value["start_char"]) is not int or type(value["end_char"]) is not int:
            validation_errors.append("start_char and end_char must be integers")
            continue
        if not isinstance(value["replacement"], str):
            validation_errors.append("replacement must be a string")
            continue
        try:
            return RelativeEdit(
                start_char=value["start_char"],
                end_char=value["end_char"],
                replacement=value["replacement"],
            )
        except ValueError as exc:
            validation_errors.append(str(exc))
    if validation_errors:
        raise ValueError(validation_errors[-1])
    if saw_object:
        raise ValueError("response does not contain a valid relative-edit JSON object")
    raise ValueError("response does not contain a JSON object")


def parse_window_rewrite(text: str) -> str:
    """Extract one exact ``corrected_window`` string from a response."""

    decoder = json.JSONDecoder()
    errors: list[str] = []
    for start, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        if set(value) != {"corrected_window"}:
            errors.append("window rewrite must contain exactly corrected_window")
            continue
        if not isinstance(value["corrected_window"], str):
            errors.append("corrected_window must be a string")
            continue
        return value["corrected_window"]
    if errors:
        raise ValueError(errors[-1])
    raise ValueError("response does not contain a window-rewrite JSON object")


def apply_model_edit(
    row: dict[str, Any],
    response: str,
    *,
    target_format: str = "relative-edit",
    context_lines: int = 8,
    max_window_chars: int = 8_000,
    max_edit_chars: int = 2_000,
) -> str:
    """Apply a model response to the complete erroneous translation unit."""

    example = make_localized_repair_example(
        row,
        context_lines=context_lines,
        max_window_chars=max_window_chars,
        max_edit_chars=max_edit_chars,
    )
    if target_format == "relative-edit":
        edit = parse_relative_edit(response)
        if edit.end_char > len(example.source_window):
            raise ValueError("predicted relative edit lies outside source window")
        predicted = LocalizedRepairExample(
            record_id=example.record_id,
            source_window=example.source_window,
            diagnostic=example.diagnostic,
            window_start_char=example.window_start_char,
            window_end_char=example.window_end_char,
            target=edit,
        )
        return apply_localized_repair(str(row["erroneous_src"]), predicted)
    if target_format == "window-rewrite":
        corrected_window = parse_window_rewrite(response)
        if len(corrected_window) > max_window_chars + max_edit_chars:
            raise ValueError("predicted corrected window exceeds safety limit")
        erroneous = str(row["erroneous_src"])
        return (
            erroneous[: example.window_start_char]
            + corrected_window
            + erroneous[example.window_end_char :]
        )
    raise ValueError(f"unknown target format: {target_format}")


def load_rows(path: str | Path, *, max_instances: int | None = None) -> list[dict]:
    if max_instances is not None and max_instances <= 0:
        raise ValueError("max_instances must be positive")
    rows: list[dict] = []
    with Path(path).open() as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at {path}:{line_number}") from exc
            if not row.get("corrected_src"):
                raise ValueError(f"unpaired row at {path}:{line_number}")
            rows.append(row)
            if max_instances is not None and len(rows) >= max_instances:
                break
    if not rows:
        raise ValueError(f"no evaluation rows found in {path}")
    return rows


def summarize_results(results: Sequence[dict[str, Any]]) -> dict[str, int | float]:
    n = len(results)
    if n == 0:
        raise ValueError("cannot summarize zero results")
    parse_ok = sum(bool(row.get("parse_ok")) for row in results)
    compile_ok = sum(bool(row.get("compile_ok")) for row in results)
    exact_match = sum(bool(row.get("exact_match")) for row in results)
    eligible_rows = [row for row in results if row.get("ground_truth_ok", True)]
    eligible = len(eligible_rows)
    eligible_compile_ok = sum(bool(row.get("compile_ok")) for row in eligible_rows)
    eligible_exact = sum(bool(row.get("exact_match")) for row in eligible_rows)
    return {
        "n": n,
        "eligible": eligible,
        "eligible_compile_ok": eligible_compile_ok,
        "eligible_exact_match": eligible_exact,
        "parse_ok": parse_ok,
        "parse_rate": parse_ok / n,
        "compile_ok": compile_ok,
        "verified_fix_rate": compile_ok / n,
        "verified_fix_rate_eligible": eligible_compile_ok / eligible if eligible else 0.0,
        "exact_match": exact_match,
        "exact_match_rate": exact_match / n,
        "exact_match_rate_eligible": eligible_exact / eligible if eligible else 0.0,
    }


def adapter_training_target_format(adapter: "str | Path | None") -> str | None:
    """The repair representation an adapter was actually trained on."""
    if adapter is None:
        return None
    manifest = Path(adapter) / "run-manifest.json"
    if not manifest.is_file():
        return None
    try:
        return json.loads(manifest.read_text()).get("target_format")
    except (OSError, json.JSONDecodeError):
        return None


def check_target_format(
    adapter: "str | Path | None", *, requested: str, allow_mismatch: bool = False,
) -> None:
    """Refuse to score an adapter in a representation it was not trained on.

    Training on ``window-rewrite`` and evaluating with ``relative-edit`` asks the
    model for an artifact it never learned to produce.  The run still completes
    and still reports a number, so the failure is indistinguishable from a
    genuinely bad model unless it is caught here.
    """
    trained = adapter_training_target_format(adapter)
    if trained is None or trained == requested or allow_mismatch:
        return
    raise ValueError(
        f"adapter was trained with target_format={trained!r} but evaluation "
        f"requested {requested!r}; pass --allow-target-format-mismatch to "
        "override deliberately"
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-model", required=True)
    parser.add_argument(
        "--adapter",
        help="Optional PEFT adapter. Omit it to evaluate the unfine-tuned base model.",
    )
    parser.add_argument("--data-path", required=True)
    parser.add_argument("--clang-bin", required=True, help="C++ compiler driver.")
    parser.add_argument(
        "--clang-c-bin",
        help="Optional C compiler driver; defaults to --clang-bin.",
    )
    parser.add_argument("--diagtool-bin", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-instances", type=int, default=8)
    parser.add_argument("--max-new-tokens", type=int, default=128)
    parser.add_argument(
        "--target-format",
        choices=("relative-edit", "window-rewrite"),
        default="relative-edit",
    )
    parser.add_argument(
        "--allow-target-format-mismatch", action="store_true",
        help="evaluate an adapter in a representation it was not trained on",
    )
    parser.add_argument("--context-lines", type=int, default=8)
    parser.add_argument("--max-window-chars", type=int, default=8_000)
    parser.add_argument("--max-edit-chars", type=int, default=2_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument(
        "--backend", choices=("local", "vllm"), default="local",
        help=(
            "local: load the model in-process with device_map=auto. That runs "
            "one layer group at a time, so a large model idles most of the "
            "node. vllm: drive an already-served model over its OpenAI API, "
            "which uses tensor parallelism across every GPU."
        ),
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument(
        "--served-model-name",
        help="Model name the server advertises; discovered from /v1/models if omitted.",
    )
    return parser.parse_args(argv)


def _load_model(args: argparse.Namespace):
    import torch
    import transformers
    from transformers import AutoConfig, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        args.base_model, local_files_only=args.local_files_only
    )
    config = AutoConfig.from_pretrained(
        args.base_model, local_files_only=args.local_files_only
    )
    architecture_name = config.architectures[0]
    architecture = getattr(transformers, architecture_name)
    base = architecture.from_pretrained(
        args.base_model,
        dtype=torch.bfloat16,
        device_map="auto",
        attn_implementation="sdpa",
        local_files_only=args.local_files_only,
    )
    model = base
    if args.adapter:
        from peft import PeftModel

        model = PeftModel.from_pretrained(base, args.adapter, is_trainable=False)
    model.eval()
    return model, tokenizer


def _generate(
    model: Any,
    tokenizer: Any,
    example: LocalizedRepairExample,
    *,
    max_new_tokens: int,
    target_format: str,
) -> str:
    import torch

    training_row = example.to_training_example()
    messages = _messages_for_example(training_row, target_format=target_format)
    encoded = tokenizer.apply_chat_template(
        messages[:-1],
        tokenize=True,
        add_generation_prompt=True,
        return_tensors="pt",
        return_dict=True,
    )
    device = next(model.parameters()).device
    encoded = {key: value.to(device) for key, value in encoded.items()}
    input_length = encoded["input_ids"].shape[-1]
    with torch.inference_mode():
        output = model.generate(
            **encoded,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=tokenizer.pad_token_id,
            eos_token_id=tokenizer.eos_token_id,
        )
    return tokenizer.decode(
        output[0, input_length:], skip_special_tokens=True
    ).strip()


def generate_via_chat_backend(
    backend: Any,
    example: LocalizedRepairExample,
    *,
    max_new_tokens: int,
    target_format: str,
) -> str:
    """Same prompt, same decoding, executed by a served model instead.

    A 31B model sharded across GPUs with ``device_map="auto"`` runs one layer
    group at a time, so seven of eight GPUs idle and a 150-instance cohort takes
    hours. Serving it with tensor parallelism uses the whole node. Only the
    execution changes: the messages come from the same builder the local path
    uses, and decoding stays greedy, or the served model would be answering a
    different exam.
    """
    training_row = example.to_training_example()
    messages = _messages_for_example(training_row, target_format=target_format)
    responses = backend.chat(
        messages=messages[:-1],
        temperature=0.0,
        max_tokens=max_new_tokens,
        n=1,
    )
    if not responses:
        raise ValueError("chat backend returned no completion")
    return (responses[0].text or "").strip()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.max_new_tokens <= 0:
        raise ValueError("max_new_tokens must be positive")
    check_target_format(
        args.adapter, requested=args.target_format,
        allow_mismatch=args.allow_target_format_mismatch,
    )

    rows = load_rows(args.data_path, max_instances=args.max_instances)
    backend = None
    model = tokenizer = None
    if args.backend == "vllm":
        from gen.fuzzlang_dsl.run_e1_experiment import served_model_name
        from repair.agent.chat_backend import OpenAIChatBackend

        backend = OpenAIChatBackend(
            model_name=args.served_model_name or served_model_name(args.base_url),
            base_url=args.base_url,
        )
    else:
        import torch

        torch.manual_seed(args.seed)
        model, tokenizer = _load_model(args)
    verifier = FuzzlangClangVerifier(
        clang_bin=args.clang_bin,
        diagtool_bin=args.diagtool_bin,
        timeout_s=30.0,
        clang_c_bin=args.clang_c_bin,
    )
    results: list[dict[str, Any]] = []
    started = time.time()
    for index, row in enumerate(rows, start=1):
        example = make_localized_repair_example(
            row,
            context_lines=args.context_lines,
            max_window_chars=args.max_window_chars,
            max_edit_chars=args.max_edit_chars,
        )
        response = (
            generate_via_chat_backend(
                backend, example,
                max_new_tokens=args.max_new_tokens,
                target_format=args.target_format,
            )
            if backend is not None else
            _generate(
                model, tokenizer, example,
                max_new_tokens=args.max_new_tokens,
                target_format=args.target_format,
            )
        )
        provenance = row.get("provenance") or {}
        detail = provenance.get("detail") or {}
        compile_cmd = detail.get("compile_cmd")
        if not isinstance(compile_cmd, list) or not compile_cmd:
            raise ValueError(f"record {row.get('record_id')} lacks compile_cmd")
        logical_path = str(
            detail.get("source_path") or provenance.get("source") or row["record_id"]
        )
        ground_truth = verifier.verify(
            str(row["corrected_src"]), compile_cmd, logical_path=logical_path
        )
        item: dict[str, Any] = {
            "record_id": row.get("record_id"),
            "diag_name": (row.get("diagnostics") or [{}])[0].get("diag_name"),
            "response": response,
            "ground_truth_ok": ground_truth.ok,
            "parse_ok": False,
            "compile_ok": False,
            "exact_match": False,
        }
        if not ground_truth.ok:
            item["ground_truth_stderr_tail"] = ground_truth.raw_stderr[-2_000:]
        try:
            predicted_src = apply_model_edit(
                row,
                response,
                target_format=args.target_format,
                context_lines=args.context_lines,
                max_window_chars=args.max_window_chars,
                max_edit_chars=args.max_edit_chars,
            )
            item["parse_ok"] = True
            item["exact_match"] = predicted_src == row["corrected_src"]
            verified = verifier.verify(
                predicted_src, compile_cmd, logical_path=logical_path
            )
            item["compile_ok"] = verified.ok
            if verified.diag is not None:
                item["result_diag_name"] = verified.diag.diag_name
                item["result_diag_msg"] = verified.diag.diag_msg
        except ValueError as exc:
            item["parse_error"] = str(exc)
        results.append(item)
        print(
            f"[adapter_eval] {index}/{len(rows)} id={row.get('record_id')} "
            f"parse={item['parse_ok']} compile={item['compile_ok']} "
            f"exact={item['exact_match']}",
            flush=True,
        )

    summary: dict[str, Any] = summarize_results(results)
    summary.update(
        {
            "base_model": args.base_model,
            "adapter": args.adapter,
            "data_path": args.data_path,
            "clang_bin": args.clang_bin,
            "clang_c_bin": args.clang_c_bin or args.clang_bin,
            "seed": args.seed,
            "max_new_tokens": args.max_new_tokens,
            "target_format": args.target_format,
            "elapsed_seconds": round(time.time() - started, 3),
            "ground_truth_compile_ok": sum(
                bool(row["ground_truth_ok"]) for row in results
            ),
        }
    )
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    with output.with_suffix(".instances.jsonl").open("w") as f:
        for result in results:
            f.write(json.dumps(result, sort_keys=True) + "\n")
    print(
        f"[adapter_eval] DONE parse={summary['parse_ok']}/{summary['n']} "
        f"compile={summary['compile_ok']}/{summary['n']} "
        f"exact={summary['exact_match']}/{summary['n']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
