"""CLI: classify catalog error diagnostics as strict C/C++ vs out-of-scope.

    PYTHONPATH=src python3 src/gen/run_scope.py \
        --out data/gen/out_of_scope.txt --model gpt-5.4-mini \
        --base-url https://api.openai.com/v1

High-precision vendor keywords mark the obvious non-C/C++ diagnostics; the rest
are judged by an LLM (batched, parallel). Writes the sorted out-of-scope
diagnostic names (one per line) — feed to
``run_coverage --exclude-names`` and to dataset filtering.
"""
from __future__ import annotations

import argparse
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from foundation.diagnostics.catalog import load_catalog
from gen.scope import (build_scope_prompt, is_obviously_out_of_scope,
                       parse_scope_verdicts)


def _chat_fn(model: str, base_url: str):
    from repair.agent.chat_backend import OpenAIChatBackend
    backend = OpenAIChatBackend(model, base_url=base_url,
                                api_key=os.environ.get("OPENAI_API_KEY", "EMPTY"))

    def chat(messages, temperature: float):
        r = backend.chat(messages=messages, temperature=temperature,
                         max_tokens=1500, n=1)
        return r[0].text if r else ""
    return chat


def main() -> None:
    ap = argparse.ArgumentParser(description="Classify diagnostics: strict C/C++ or not.")
    ap.add_argument("--out", type=Path, required=True, help="out-of-scope names file")
    ap.add_argument("--model", default="gpt-5.4-mini")
    ap.add_argument("--base-url", default="https://api.openai.com/v1")
    ap.add_argument("--batch", type=int, default=20)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--temperature", type=float, default=1.0)
    args = ap.parse_args()

    errors = [(e.name, e.message or "") for e in load_catalog().errors()]
    out_of_scope: set[str] = set()

    # 1) keyword pass — obvious vendor/dialect/target diagnostics.
    todo = []
    for name, msg in errors:
        if is_obviously_out_of_scope(name):
            out_of_scope.add(name)
        else:
            todo.append((name, msg))
    print(f"[scope] {len(errors)} diagnostics; {len(out_of_scope)} out by keyword; "
          f"{len(todo)} to LLM-judge")

    # 2) LLM pass over the rest (batched, parallel). Default missing verdicts to
    #    IN (keep) — conservative: don't drop a diagnostic we're unsure about.
    chat = _chat_fn(args.model, args.base_url)
    batches = [todo[i:i + args.batch] for i in range(0, len(todo), args.batch)]

    def judge(batch):
        try:
            reply = chat(build_scope_prompt(batch), args.temperature)
        except Exception:
            return []
        verdicts = parse_scope_verdicts(reply, len(batch))
        return [batch[i][0] for i, in_scope in verdicts.items() if not in_scope]

    llm_out: list[str] = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, names in enumerate(ex.map(judge, batches), 1):
            llm_out.extend(names)
            if i % 20 == 0:
                print(f"  ... {i}/{len(batches)} batches")
    out_of_scope.update(llm_out)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(sorted(out_of_scope)) + "\n")
    print(f"[scope] out-of-scope: {len(out_of_scope)} "
          f"(keyword {len(out_of_scope) - len(llm_out)}, llm {len(llm_out)}); "
          f"in-scope: {len(errors) - len(out_of_scope)}")
    print(f"[scope] -> {args.out}")


if __name__ == "__main__":
    main()
