"""Versioned FuzzLang DSL schema and compatibility adapter.

Version 1 adds deterministic payload-local fresh identifiers while retaining
the deliberately narrow lexical transformation model from version 0.  It does
not evaluate generated code or implement an AST, type, or symbol-table
transformation language.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from gen.realcorpus.recipes import (
    LearnedRecipe,
    LexToken,
    RecipeApplication,
    apply_recipe,
)


FUZZLANG_DSL_SCHEMA = "fuzzlang.injector"
FUZZLANG_DSL_VERSION = 2
_SUPPORTED_VERSIONS = frozenset({0, 1, 2})

_OPERATIONS = frozenset({"append", "insert", "delete", "replace"})
_LANGUAGES = frozenset({"c", "c++", "objective-c", "objective-c++"})
_PART_KINDS_BY_VERSION = {
    0: frozenset({"literal", "binding"}),
    1: frozenset({"literal", "binding", "fresh"}),
    2: frozenset({"literal", "binding", "fresh"}),
}
_BINDING_RE = re.compile(r"ID\d+")
_FRESH_RE = re.compile(r"FRESH\d+")
_BOUND_PATTERN_RE = re.compile(r"<(ID\d+)>")


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


@dataclass(frozen=True)
class ReplayLimits:
    """Safety and budget limits carried by an Injector artifact."""

    max_edit_chars: int = 256
    max_candidates: int = 8
    max_verifications: int = 50

    def __post_init__(self) -> None:
        for name in (
            "max_edit_chars", "max_candidates", "max_verifications",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

    def to_dict(self) -> dict[str, int]:
        return {
            "max_edit_chars": self.max_edit_chars,
            "max_candidates": self.max_candidates,
            "max_verifications": self.max_verifications,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReplayLimits":
        return cls(
            max_edit_chars=value.get("max_edit_chars", 256),
            max_candidates=value.get("max_candidates", 8),
            max_verifications=value.get("max_verifications", 50),
        )


@dataclass(frozen=True)
class FuzzLangInjector:
    """One diagnostic-specific FuzzLang DSL transformation.

    ``injector_id`` hashes transformation semantics and the edit safety bound.
    Evidence metadata and per-run replay budgets are intentionally excluded,
    so accumulating support or scaling a run does not rename an otherwise
    unchanged Injector.  ``content_hash`` covers the complete serialized
    artifact when byte-level provenance matters.
    """

    target_diag: str
    language: str
    operation: str
    old_patterns: tuple[str, ...]
    new_text: str
    left_context: tuple[str, ...]
    right_context: tuple[str, ...]
    portable: bool
    replacement_parts: tuple[tuple[str, str], ...] = ()
    target_diag_id: Optional[int] = None
    limits: ReplayLimits = field(default_factory=ReplayLimits)
    support: int = 1
    exemplar_ids: tuple[str, ...] = ()
    source_recipe_id: Optional[str] = None
    schema: str = field(default=FUZZLANG_DSL_SCHEMA, init=False)
    schema_version: int = FUZZLANG_DSL_VERSION
    injector_id: str = field(init=False)

    def __post_init__(self) -> None:
        for name in (
            "old_patterns", "left_context", "right_context", "exemplar_ids",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(
            self,
            "replacement_parts",
            tuple(tuple(part) for part in self.replacement_parts),
        )
        self._validate()
        digest = hashlib.sha256(
            _canonical_json(self._identity_dict()).encode("utf-8")
        ).hexdigest()
        object.__setattr__(
            self,
            "injector_id",
            f"fuzzlang-v{self.schema_version}-{digest[:16]}",
        )

    def _validate(self) -> None:
        if not isinstance(self.target_diag, str) or not self.target_diag:
            raise ValueError("target_diag must be a non-empty string")
        if (isinstance(self.schema_version, bool)
                or not isinstance(self.schema_version, int)
                or self.schema_version not in _SUPPORTED_VERSIONS):
            raise ValueError(
                f"unsupported FuzzLang DSL version: {self.schema_version!r}"
            )
        if self.target_diag_id is not None and (
            isinstance(self.target_diag_id, bool)
            or not isinstance(self.target_diag_id, int)
            or self.target_diag_id < 0
        ):
            raise ValueError("target_diag_id must be a non-negative integer or null")
        if self.language not in _LANGUAGES:
            raise ValueError(f"unsupported FuzzLang DSL language: {self.language!r}")
        if self.operation not in _OPERATIONS:
            raise ValueError(f"unsupported FuzzLang DSL operation: {self.operation!r}")
        for name in ("old_patterns", "left_context", "right_context"):
            values = getattr(self, name)
            if any(not isinstance(value, str) or not value for value in values):
                raise ValueError(f"{name} must contain non-empty strings")
        if not isinstance(self.new_text, str):
            raise ValueError("new_text must be a string")
        if not isinstance(self.portable, bool):
            raise ValueError("portable must be a boolean")
        if isinstance(self.support, bool) or not isinstance(self.support, int):
            raise ValueError("support must be a positive integer")
        if self.support <= 0:
            raise ValueError("support must be a positive integer")
        if any(not isinstance(value, str) or not value for value in self.exemplar_ids):
            raise ValueError("exemplar_ids must contain non-empty strings")
        if self.source_recipe_id is not None and (
            not isinstance(self.source_recipe_id, str) or not self.source_recipe_id
        ):
            raise ValueError("source_recipe_id must be a non-empty string or null")
        if not isinstance(self.limits, ReplayLimits):
            raise ValueError("limits must be ReplayLimits")
        if self.operation in {"insert", "append"} and self.old_patterns:
            raise ValueError("insert operations cannot carry old_patterns")
        if self.operation not in {"insert", "append"} and not self.old_patterns:
            raise ValueError(f"{self.operation} operations require old_patterns")
        if self.operation == "append" and (
            self.left_context or self.right_context
        ):
            raise ValueError("append operations cannot carry lexical context")
        if self.operation == "append" and not self.new_text:
            raise ValueError("append operations require a non-empty payload")
        if self.operation == "delete" and self.new_text:
            raise ValueError("delete operations require an empty new_text")
        if self.portable and len(self.new_text) > self.limits.max_edit_chars:
            raise ValueError("new_text exceeds max_edit_chars")

        bound_labels = {
            match.group(1)
            for pattern in (
                self.left_context + self.old_patterns + self.right_context
            )
            if (match := _BOUND_PATTERN_RE.fullmatch(pattern)) is not None
        }
        for part in self.replacement_parts:
            if len(part) != 2:
                raise ValueError("replacement parts must be (kind, value) pairs")
            kind, value = part
            if (kind not in _PART_KINDS_BY_VERSION[self.schema_version]
                    or not isinstance(value, str)):
                raise ValueError(f"invalid replacement part: {part!r}")
            if kind == "binding":
                if not _BINDING_RE.fullmatch(value):
                    raise ValueError(f"invalid replacement binding {value!r}")
                if value not in bound_labels:
                    raise ValueError(
                        f"replacement binding {value} is absent from match patterns"
                    )
            elif kind == "fresh" and not _FRESH_RE.fullmatch(value):
                raise ValueError(f"invalid fresh identifier label {value!r}")
        if self.operation == "delete" and any(
            kind != "literal" or value for kind, value in self.replacement_parts
        ):
            raise ValueError("delete operations cannot carry a replacement")

    def _identity_dict(self) -> dict[str, Any]:
        """Return fields that define transformation identity."""
        return {
            "schema": self.schema,
            "schema_version": self.schema_version,
            "target": {
                "diag_name": self.target_diag,
                "diag_id": self.target_diag_id,
            },
            "language": self.language,
            "match": {
                "left_context": list(self.left_context),
                "old_patterns": list(self.old_patterns),
                "right_context": list(self.right_context),
            },
            "edit": {
                "operation": self.operation,
                "replacement_parts": [
                    {"kind": kind, "value": value}
                    for kind, value in self.replacement_parts
                ],
            },
            "portable": self.portable,
            "limits": {"max_edit_chars": self.limits.max_edit_chars},
        }

    def to_dict(self) -> dict[str, Any]:
        """Return the versioned JSON-ready representation."""
        value = self._identity_dict()
        value["injector_id"] = self.injector_id
        value["limits"] = self.limits.to_dict()
        value["edit"]["exemplar_replacement"] = self.new_text
        value["provenance"] = {
            "source_recipe_id": self.source_recipe_id,
            "support": self.support,
            "exemplar_ids": list(self.exemplar_ids),
        }
        return value

    def to_json(self) -> str:
        """Serialize canonically for stable archives and checksums."""
        return _canonical_json(self.to_dict())

    @property
    def content_hash(self) -> str:
        """SHA-256 of the complete canonical serialized artifact."""
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FuzzLangInjector":
        if value.get("schema") != FUZZLANG_DSL_SCHEMA:
            raise ValueError(f"unsupported FuzzLang DSL schema: {value.get('schema')!r}")
        schema_version = value.get("schema_version")
        if (isinstance(schema_version, bool)
                or not isinstance(schema_version, int)
                or schema_version not in _SUPPORTED_VERSIONS):
            raise ValueError(
                f"unsupported FuzzLang DSL version: {schema_version!r}"
            )
        try:
            target = value["target"]
            match = value["match"]
            edit = value["edit"]
        except KeyError as error:
            raise ValueError(f"missing FuzzLang DSL field: {error.args[0]}") from error
        provenance = value.get("provenance", {})
        try:
            parts = tuple(
                (part["kind"], part["value"])
                for part in edit.get("replacement_parts", ())
            )
            injector = cls(
                target_diag=target["diag_name"],
                target_diag_id=target.get("diag_id"),
                language=value["language"],
                operation=edit["operation"],
                old_patterns=tuple(match.get("old_patterns", ())),
                new_text=edit.get("exemplar_replacement", ""),
                left_context=tuple(match.get("left_context", ())),
                right_context=tuple(match.get("right_context", ())),
                portable=value.get("portable", True),
                replacement_parts=parts,
                limits=ReplayLimits.from_dict(value.get("limits", {})),
                support=provenance.get("support", 1),
                exemplar_ids=tuple(provenance.get("exemplar_ids", ())),
                source_recipe_id=provenance.get("source_recipe_id"),
                schema_version=schema_version,
            )
        except (KeyError, TypeError) as error:
            raise ValueError(f"invalid FuzzLang DSL object: {error}") from error
        supplied_id = value.get("injector_id")
        if supplied_id is not None and supplied_id != injector.injector_id:
            raise ValueError(
                "injector_id does not match the canonical transformation identity"
            )
        return injector

    @classmethod
    def from_json(cls, value: str) -> "FuzzLangInjector":
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid FuzzLang DSL JSON: {error}") from error
        if not isinstance(decoded, dict):
            raise ValueError("a FuzzLang DSL Injector must be a JSON object")
        return cls.from_dict(decoded)

    @classmethod
    def from_recipe(
        cls,
        recipe: LearnedRecipe,
        *,
        diag_id: Optional[int] = None,
        limits: Optional[ReplayLimits] = None,
    ) -> "FuzzLangInjector":
        """Convert an existing learned recipe without changing its semantics."""
        if not isinstance(recipe, LearnedRecipe):
            raise TypeError("recipe must be a LearnedRecipe")
        return cls(
            target_diag=recipe.diag_name,
            target_diag_id=diag_id,
            language=recipe.language,
            operation=recipe.operation,
            old_patterns=recipe.old_patterns,
            new_text=recipe.new_text,
            left_context=recipe.left_context,
            right_context=recipe.right_context,
            portable=recipe.portable,
            replacement_parts=recipe.replacement_parts,
            limits=limits or ReplayLimits(),
            support=recipe.support,
            exemplar_ids=recipe.exemplar_ids,
            source_recipe_id=recipe.recipe_id,
        )

    @classmethod
    def from_recipe_dict(
        cls,
        value: Mapping[str, Any],
        *,
        diag_id: Optional[int] = None,
        limits: Optional[ReplayLimits] = None,
    ) -> "FuzzLangInjector":
        """Load v1/v2 recipe JSON through its backward-compatible parser."""
        return cls.from_recipe(
            LearnedRecipe.from_dict(dict(value)),
            diag_id=diag_id,
            limits=limits,
        )

    @classmethod
    def append_fragment(
        cls,
        *,
        target_diag: str,
        language: str,
        fragment: str,
        diag_id: Optional[int] = None,
        limits: Optional[ReplayLimits] = None,
        exemplar_id: Optional[str] = None,
    ) -> "FuzzLangInjector":
        """Create a bounded, replayable end-of-translation-unit Injector."""
        return cls(
            target_diag=target_diag,
            target_diag_id=diag_id,
            language=language,
            operation="append",
            old_patterns=(),
            new_text=fragment,
            left_context=(),
            right_context=(),
            portable=True,
            replacement_parts=(("literal", fragment),),
            limits=limits or ReplayLimits(),
            exemplar_ids=(exemplar_id,) if exemplar_id else (),
            schema_version=2,
        )

    def to_recipe(self, *, use_injector_id: bool = False) -> LearnedRecipe:
        """Convert to the existing replay type.

        The legacy ID is retained for a lossless compatibility round trip.
        Injector replay opts into the immutable Injector ID instead.
        """
        recipe_id = (
            self.injector_id if use_injector_id
            else (self.source_recipe_id or self.injector_id)
        )
        return LearnedRecipe(
            recipe_id=recipe_id,
            diag_name=self.target_diag,
            language=self.language,
            operation=self.operation,
            old_patterns=self.old_patterns,
            new_text=self.new_text,
            left_context=self.left_context,
            right_context=self.right_context,
            portable=self.portable,
            replacement_parts=self.replacement_parts,
            support=self.support,
            exemplar_ids=self.exemplar_ids,
        )


def apply_injector(
    source: str,
    injector: FuzzLangInjector,
    *,
    max_candidates: Optional[int] = None,
    tokens: Optional[list[LexToken]] = None,
    token_index: Optional[dict[str, tuple[int, ...]]] = None,
) -> list[RecipeApplication]:
    """Replay a supported DSL version through the bounded lexical matcher."""
    if not isinstance(injector, FuzzLangInjector):
        raise TypeError("injector must be a FuzzLangInjector")
    requested = injector.limits.max_candidates
    if max_candidates is not None:
        if max_candidates <= 0:
            return []
        requested = min(requested, max_candidates)
    if injector.operation == "append":
        if requested <= 0:
            return []
        separator = "" if source.endswith("\n") else "\n"
        appended = source + separator + injector.new_text
        return [RecipeApplication(
            src=appended,
            start=len(source),
            end=len(source),
            replacement=injector.new_text,
            recipe_id=injector.injector_id,
        )]
    recipe = injector.to_recipe(use_injector_id=True)
    applications = apply_recipe(
        source,
        recipe,
        max_candidates=requested,
        tokens=tokens,
        token_index=token_index,
    )
    # Extracted recipes already satisfy this bound.  Recheck concrete target
    # spans and rendered identifiers because serialized Injectors are replayed
    # on source text that was not present at extraction time.
    return [
        application for application in applications
        if application.end - application.start <= injector.limits.max_edit_chars
        and len(application.replacement) <= injector.limits.max_edit_chars
    ]
