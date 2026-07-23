"""Derive distinct FuzzLang DSL context levels from a paired seed record."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from foundation.record import Record
from gen.fuzzlang_dsl.injector import FuzzLangInjector
from gen.realcorpus.recipes import extract_recipe


DEFAULT_RECIPE_CONTEXT_TOKENS = (0, 1, 2)


def load_excluded_injector_ids(paths: Iterable[Path]) -> tuple[str, ...]:
    """Load canonical Injector identities already emitted by earlier runs."""
    identities: set[str] = set()
    for path in paths:
        for line in path.read_text().splitlines():
            if line.strip():
                identities.add(FuzzLangInjector.from_dict(json.loads(line)).injector_id)
    return tuple(sorted(identities))


def extract_contextual_injectors(
    record: Record,
    *,
    diag_id: int | None,
    context_tokens: Iterable[int],
) -> tuple[FuzzLangInjector, ...]:
    """Distil one exact witness into separately identified context levels."""
    injectors: dict[str, FuzzLangInjector] = {}
    for level in sorted(set(context_tokens)):
        recipe = extract_recipe(
            record,
            context_tokens=level,
            allow_fresh_identifiers=True,
            allow_literal_payloads=True,
            normalize_token_edits=True,
        )
        if recipe is None or not recipe.portable:
            continue
        injector = FuzzLangInjector.from_recipe(recipe, diag_id=diag_id)
        injectors[injector.injector_id] = injector
    return tuple(injectors.values())
