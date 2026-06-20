"""The FuzzLang dataset record schema.

One record pairs an erroneous program with the correct, compiling program the
error was introduced into, plus the diagnostic(s) the error triggers and where
it came from. This is the shared unit Gen produces, Real harvests, Repair
consumes, and Coverage counts.

Defining invariant (the meaning of the name): errors are introduced into
*correct* code, so every **core** record carries a corrected version. Material
without a corrected counterpart is not a core record; it may live only in the
AUXILIARY split. See docs/FuzzLang-Proposal.md §5/§6.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Optional

from foundation.types import DiagInfo


class Origin(str, Enum):
    """How a record was produced."""

    MUTATE = "mutate"   # mechanical mutation of correct code
    GUIDED = "guided"   # mutation guided by the compiler's tests/commits
    LLM = "llm"         # model-assisted mutation
    REAL = "real"       # mined from a real project's failing commit


class Split(str, Enum):
    """Which partition a record belongs to."""

    TRAIN = "train"
    DEV = "dev"
    EVAL = "eval"
    AUXILIARY = "auxiliary"   # broken-only material; never a core paired example


@dataclass(frozen=True)
class Provenance:
    """Where a record came from, for traceability and split isolation."""

    origin: Origin
    source: str                                # correct-code origin, or "project@sha"
    detail: dict = field(default_factory=dict)  # extra: mutation kind, fix_sha, etc.


@dataclass(frozen=True)
class Record:
    record_id: str
    erroneous_src: str
    corrected_src: Optional[str]
    diagnostics: tuple[DiagInfo, ...]
    provenance: Provenance
    split: Split
    language: str = "c++"

    def __post_init__(self) -> None:
        # Coerce a list of diagnostics to a tuple so callers need not.
        if not isinstance(self.diagnostics, tuple):
            object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        if not self.erroneous_src:
            raise ValueError("erroneous_src must be non-empty")
        if not self.diagnostics:
            raise ValueError("a record must carry at least one diagnostic")
        if self.is_core and not self.corrected_src:
            raise ValueError(
                f"core record {self.record_id!r} (split={self.split.value}) requires "
                "corrected_src; broken-only material must use Split.AUXILIARY"
            )

    @property
    def is_core(self) -> bool:
        """A core record is a paired example; AUXILIARY records are not."""
        return self.split is not Split.AUXILIARY

    @property
    def primary_diagnostic(self) -> Optional[DiagInfo]:
        return self.diagnostics[0] if self.diagnostics else None

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "erroneous_src": self.erroneous_src,
            "corrected_src": self.corrected_src,
            "diagnostics": [asdict(d) for d in self.diagnostics],
            "provenance": {
                "origin": self.provenance.origin.value,
                "source": self.provenance.source,
                "detail": self.provenance.detail,
            },
            "split": self.split.value,
            "language": self.language,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Record":
        prov = d["provenance"]
        return cls(
            record_id=d["record_id"],
            erroneous_src=d["erroneous_src"],
            corrected_src=d.get("corrected_src"),
            diagnostics=tuple(DiagInfo(**dd) for dd in d["diagnostics"]),
            provenance=Provenance(
                origin=Origin(prov["origin"]),
                source=prov["source"],
                detail=prov.get("detail", {}),
            ),
            split=Split(d["split"]),
            language=d.get("language", "c++"),
        )
