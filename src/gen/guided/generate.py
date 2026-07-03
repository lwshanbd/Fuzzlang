"""Guided pair generation: prompt an LLM, verify its output, emit a Record.

The LLM is injected as a `chat` callable (`list[message] -> reply text`) so this
module stays independent of any particular backend (`repair`'s OpenAI client,
a local vLLM endpoint, or a fake in tests). The correct-code invariant is
enforced here just like `gen.collect`: the correct version must compile and the
broken version must trigger a real diagnostic, or no record is produced.
"""
from __future__ import annotations

import hashlib
import re
from typing import Callable, Optional, Sequence

from foundation.record import Origin, Provenance, Record, Split
from foundation.verifier.base import BaseVerifier
from gen.collect import default_compile_cmd
from gen.guided.prompt import build_pair_prompt

ChatFn = Callable[[list[dict]], str]

_FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)


def parse_pair(reply: str) -> Optional[tuple[str, str]]:
    """Extract (correct_src, broken_src) from the first two fenced code blocks."""
    blocks = [b.strip() for b in _FENCE_RE.findall(reply)]
    if len(blocks) < 2 or not blocks[0] or not blocks[1]:
        return None
    return blocks[0], blocks[1]


def _record_id(source: str, diag_name: str, broken: str) -> str:
    h = hashlib.sha256(f"{source}|{diag_name}|{broken}".encode()).hexdigest()
    return f"guided-{h[:12]}"


def _lang_of_cmd(cmd: list[str]) -> Optional[str]:
    for i, tok in enumerate(cmd):
        if tok == "-x" and i + 1 < len(cmd):
            return cmd[i + 1]
    return None


def generate_pair(
    diag_name: str,
    msg_template: str,
    example: str,
    chat: ChatFn,
    verifier: BaseVerifier,
    *,
    source: str,
    language: str = "c++",
    split: Split = Split.TRAIN,
    compile_cmd: Optional[list[str]] = None,
    compile_cmds: Optional[list[list[str]]] = None,
    logical_path: Optional[str] = None,
    target_required: bool = False,
    extra: str = "",
) -> Optional[Record]:
    """Ask the LLM for a correct/broken pair for `diag_name`; verify; return a Record.

    Verification tries each config in `compile_cmds` (defaults to a single
    `compile_cmd`/language) and keeps the pair under the first config where the
    correct version compiles and the broken version triggers an error — so a
    C/Objective-C diagnostic is verified under the right language. The record's
    `language` is taken from the winning config.

    Returns None if the reply is unparseable, or no config yields a
    correct-compiles + broken-errors pair (respecting `target_required`).
    """
    pair = parse_pair(chat(build_pair_prompt(diag_name, msg_template, example,
                                             language, extra=extra)))
    if pair is None:
        return None
    correct_src, broken_src = pair

    cmds = compile_cmds if compile_cmds is not None else [
        compile_cmd if compile_cmd is not None else default_compile_cmd(language)
    ]
    lpath = logical_path if logical_path is not None else source

    for cmd in cmds:
        if not verifier.verify(correct_src, cmd, logical_path=lpath).ok:
            continue
        result = verifier.verify(broken_src, cmd, logical_path=lpath)
        if result.ok or result.diag is None:
            continue
        if target_required and result.diag.diag_name != diag_name:
            continue
        return Record(
            record_id=_record_id(source, result.diag.diag_name or diag_name, broken_src),
            erroneous_src=broken_src,
            corrected_src=correct_src,
            diagnostics=(result.diag,),
            provenance=Provenance(
                origin=Origin.GUIDED,
                source=source,
                detail={
                    "target_diag": diag_name,
                    "matched_target": result.diag.diag_name == diag_name,
                },
            ),
            split=split,
            language=_lang_of_cmd(cmd) or language,
        )
    return None


def generate_pairs(
    diag_name: str,
    msg_template: str,
    examples: Sequence[str],
    chat: ChatFn,
    verifier: BaseVerifier,
    *,
    source: str,
    language: str = "c++",
    split: Split = Split.TRAIN,
    compile_cmd: Optional[list[str]] = None,
    compile_cmds: Optional[list[list[str]]] = None,
    logical_path: Optional[str] = None,
    target_required: bool = False,
    samples: int = 1,
    extra: str = "",
) -> list[Record]:
    """Make up to `samples` distinct verified pairs for one diagnostic.

    Each attempt cycles through `examples` (temperature diversity in `chat`
    supplies the variety) and calls :func:`generate_pair`. Records with an
    erroneous source already produced for this diagnostic are dropped, so the
    result raises multiplicity without emitting duplicate broken programs.
    """
    out: list[Record] = []
    seen: set[str] = set()
    for k in range(max(1, samples)):
        example = examples[k % len(examples)] if examples else ""
        rec = generate_pair(
            diag_name, msg_template, example, chat, verifier,
            source=source, language=language, split=split,
            compile_cmd=compile_cmd, compile_cmds=compile_cmds,
            logical_path=logical_path, target_required=target_required,
            extra=extra,
        )
        if rec is not None and rec.erroneous_src not in seen:
            seen.add(rec.erroneous_src)
            out.append(rec)
    return out
