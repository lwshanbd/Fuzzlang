"""Verify an injected mutant with the real compile command and emit a Record.

Keep iff the mutant errors with a usable primary diagnostic (the TU already
compiled clean when the fragment was indexed). Tag cascade size and whether the
primary diagnostic matches the requested target.
"""
from __future__ import annotations

import hashlib
import re
from typing import Optional

from foundation.record import Origin, Provenance, Record, Split
from foundation.types import VerifierResult
from foundation.verifier.base import BaseVerifier
from gen.realcorpus.corpus import Fragment
from gen.realcorpus.targets import Target

_ERROR_LINE = re.compile(r"^[^:\n]+:\d+:\d+:\s*(?:fatal\s+)?error:", re.MULTILINE)


def count_errors(stderr: str) -> int:
    return len(_ERROR_LINE.findall(stderr))


def _record_id(rel_path: str, target: str, mutant: str) -> str:
    h = hashlib.sha256(f"{rel_path}|{target}|{mutant}".encode()).hexdigest()[:12]
    return f"realinject-{h}"


def collect_real_record(
    fragment: Fragment,
    erroneous_src: str,
    target: Target,
    verifier: BaseVerifier,
    *,
    split: Split = Split.EVAL,
    language: str = "c++",
    result: Optional[VerifierResult] = None,
) -> Optional[Record]:
    res = result if result is not None else verifier.verify(
        erroneous_src, fragment.compile_cmd, logical_path=fragment.rel_path)
    if res.ok or res.diag is None:
        return None
    cascade = count_errors(res.raw_stderr)
    matches = res.diag.diag_name == target.name
    return Record(
        record_id=_record_id(fragment.rel_path, target.name, erroneous_src),
        erroneous_src=erroneous_src,
        corrected_src=fragment.tu_src,
        diagnostics=(res.diag,),
        provenance=Provenance(
            origin=Origin.GUIDED,
            source=f"llvm:{fragment.rel_path}",
            detail={
                "strategy": "realcorpus_inject",
                "target_diag": target.name,
                "primary_matches_target": matches,
                "cascade_size": cascade,
                "region": list(fragment.span),
            },
        ),
        split=split,
        language=language,
    )
