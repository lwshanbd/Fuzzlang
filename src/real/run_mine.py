"""CLI: mine real compile errors from GitHub PRs/issues (local, DeepSeek-assisted).

    OPENAI_API_KEY=<deepseek key> PYTHONPATH=src python3 src/real/run_mine.py \
        --repo llvm/llvm-project --out data/real/llvm.jsonl \
        --model deepseek-chat --base-url https://api.deepseek.com \
        --query "does not compile" --limit 40

Clone-free: uses the authenticated `gh` CLI to search merged PRs, fetch each
one's title+body+comments+diff, and asks DeepSeek to extract the compiler error
plus the broken/fixed code. The diagnostic matcher names the error. Emits
Record(Origin.REAL) rows (Column B). Needs `gh auth login`, `pip install openai`,
and a DeepSeek API key in OPENAI_API_KEY.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from foundation.diagnostics.catalog import load_catalog
from foundation.diagnostics.matcher import DiagnosticMatcher
from real.mine import extract_from_text, looks_like_compile_error


def _gh_json(args: list[str]):
    out = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {out.stderr.strip()}")
    return json.loads(out.stdout) if out.stdout.strip() else None


def search_prs(repo: str, query: str, limit: int) -> list[dict]:
    return _gh_json(["search", "prs", "--repo", repo, "--merged", "--limit",
                     str(limit), "--json", "number,title,url", query]) or []


def fetch_pr_text(repo: str, number: int) -> str:
    view = _gh_json(["pr", "view", str(number), "--repo", repo,
                     "--json", "title,body,comments"]) or {}
    parts = [view.get("title", ""), view.get("body", "")]
    parts += [c.get("body", "") for c in view.get("comments", [])]
    diff = subprocess.run(["gh", "pr", "diff", str(number), "--repo", repo],
                          capture_output=True, text=True, timeout=120)
    if diff.returncode == 0:
        parts.append("DIFF:\n" + diff.stdout[:20000])
    return "\n\n".join(p for p in parts if p)


def search_issues(repo: str, query: str, limit: int) -> list[dict]:
    return _gh_json(["search", "issues", "--repo", repo, "--limit", str(limit),
                     "--json", "number,title,url", query]) or []


def fetch_issue_text(repo: str, number: int) -> str:
    view = _gh_json(["issue", "view", str(number), "--repo", repo,
                     "--json", "title,body,comments"]) or {}
    parts = [view.get("title", ""), view.get("body", "")]
    parts += [c.get("body", "") for c in view.get("comments", [])]
    return "\n\n".join(p for p in parts if p)


def _build_chat(base_url: str, model: str, max_tokens: int, temperature: float):
    """A minimal OpenAI-compatible chat client using only the stdlib (no openai pkg).

    Reads the API key from DEEPSEEK_API_KEY or OPENAI_API_KEY. Works against
    DeepSeek (https://api.deepseek.com) or any OpenAI-compatible endpoint.
    """
    import urllib.request

    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY", "EMPTY")
    url = base_url.rstrip("/") + "/chat/completions"

    def chat(messages):
        body = json.dumps({
            "model": model, "messages": messages,
            "temperature": temperature, "max_tokens": max_tokens,
        }).encode()
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {api_key}"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"]

    return chat


def main() -> None:
    ap = argparse.ArgumentParser(description="Mine real compile errors from GitHub -> JSONL.")
    ap.add_argument("--repo", required=True, help="owner/name, e.g. llvm/llvm-project")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--query", default="does not compile",
                    help="search query (title/body match)")
    ap.add_argument("--source", choices=["prs", "issues", "both"], default="both",
                    help="mine merged PRs, issues, or both")
    ap.add_argument("--limit", type=int, default=40, help="candidates per source")
    ap.add_argument("--model", default="deepseek-chat")
    ap.add_argument("--base-url", default="https://api.deepseek.com")
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--temperature", type=float, default=0.2)
    args = ap.parse_args()

    matcher = DiagnosticMatcher(load_catalog())
    chat = _build_chat(args.base_url, args.model, args.max_tokens, args.temperature)

    candidates: list[tuple[str, int, str]] = []
    if args.source in ("prs", "both"):
        candidates += [("pr", p["number"], p.get("url", ""))
                       for p in search_prs(args.repo, args.query, args.limit)]
    if args.source in ("issues", "both"):
        candidates += [("issue", i["number"], i.get("url", ""))
                       for i in search_issues(args.repo, args.query, args.limit)]
    print(f"[run_mine] {len(candidates)} candidates in {args.repo} (source={args.source})")

    records, filtered = [], 0
    for kind, n, url in candidates:
        try:
            text = fetch_pr_text(args.repo, n) if kind == "pr" else fetch_issue_text(args.repo, n)
        except (RuntimeError, subprocess.TimeoutExpired):
            print(f"  [{kind}#{n}] fetch failed")
            continue
        if not looks_like_compile_error(text):
            filtered += 1
            continue  # cheap skip: no compiler-error signature, no LLM call
        rec = extract_from_text(text, chat, matcher=matcher, project=args.repo,
                                ref=f"{kind}/{n}", url=url)
        if rec is not None:
            records.append(rec)
        print(f"  [{kind}#{n}] {'ok ' + (rec.primary_diagnostic.diag_name or 'unnamed') if rec else 'skip'}")
    print(f"[run_mine] prefiltered out {filtered} non-compile candidates (saved LLM calls)")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r.to_dict()) + "\n")
    print(f"[run_mine] wrote {len(records)}/{len(candidates)} records -> {args.out}")


if __name__ == "__main__":
    main()
