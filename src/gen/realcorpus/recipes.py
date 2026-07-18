"""Learn diagnostic-specific source transformers from verified source pairs.

Each recipe is the minimal corrected->erroneous edit plus a short lexical
context.  User identifiers and numeric literals in the context become
placeholders, while language keywords and punctuation stay exact.  This makes
small edits such as ``return x`` -> ``return &x`` replayable on a different TU
without carrying source code from the exemplar into the generated record.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from typing import Iterable, Optional

from foundation.record import Record
from gen.mutate._scan import code_mask


_TOKEN_RE = re.compile(
    r"[A-Za-z_]\w*|(?:0[xX][0-9A-Fa-f]+|\d+(?:\.\d*)?)|"
    r">>=|<<=|->\*|\.\.\.|::|->|\+\+|--|&&|\|\||==|!=|<=|>=|"
    r"\+=|-=|\*=|/=|%=|&=|\|=|\^=|<<|>>|##|[^\s]"
)

# C23 + C++23 keywords.  Exact keyword matching carries the syntactic shape;
# non-keyword identifiers are intentionally abstracted to <ID>.
_KEYWORDS = frozenset("""
alignas alignof and and_eq asm atomic_cancel atomic_commit atomic_noexcept auto
bitand bitor bool break case catch char char8_t char16_t char32_t class compl
concept const consteval constexpr constinit const_cast continue co_await co_return
co_yield decltype default delete do double dynamic_cast else enum explicit
export extern false float for friend goto if inline int long mutable namespace
new noexcept not not_eq nullptr operator or or_eq private protected public
reflexpr register reinterpret_cast requires return short signed sizeof static
static_assert static_cast struct switch synchronized template this thread_local
throw true try typedef typeid typename union unsigned using virtual void volatile
wchar_t while xor xor_eq _Alignas _Alignof _Atomic _BitInt _Bool _Complex
_Decimal32 _Decimal64 _Decimal128 _Generic _Imaginary _Noreturn _Static_assert
_Thread_local
""".split())


@dataclass(frozen=True)
class LexToken:
    text: str
    start: int
    end: int
    pattern: str


@dataclass(frozen=True)
class LearnedRecipe:
    recipe_id: str
    diag_name: str
    language: str
    operation: str
    old_patterns: tuple[str, ...]
    new_text: str
    left_context: tuple[str, ...]
    right_context: tuple[str, ...]
    portable: bool
    support: int = 1
    exemplar_ids: tuple[str, ...] = ()

    def identity(self) -> tuple:
        return (
            self.diag_name, self.language, self.operation, self.old_patterns,
            self.new_text, self.left_context, self.right_context, self.portable,
        )

    def to_dict(self) -> dict:
        return {
            "recipe_id": self.recipe_id,
            "diag_name": self.diag_name,
            "language": self.language,
            "operation": self.operation,
            "old_patterns": list(self.old_patterns),
            "new_text": self.new_text,
            "left_context": list(self.left_context),
            "right_context": list(self.right_context),
            "portable": self.portable,
            "support": self.support,
            "exemplar_ids": list(self.exemplar_ids),
        }

    @classmethod
    def from_dict(cls, value: dict) -> "LearnedRecipe":
        return cls(
            recipe_id=value["recipe_id"],
            diag_name=value["diag_name"],
            language=value.get("language", "c++"),
            operation=value["operation"],
            old_patterns=tuple(value.get("old_patterns", ())),
            new_text=value.get("new_text", ""),
            left_context=tuple(value.get("left_context", ())),
            right_context=tuple(value.get("right_context", ())),
            portable=bool(value.get("portable", False)),
            support=int(value.get("support", 1)),
            exemplar_ids=tuple(value.get("exemplar_ids", ())),
        )


@dataclass(frozen=True)
class RecipeApplication:
    src: str
    start: int
    end: int
    replacement: str
    recipe_id: str


def minimal_edit(corrected: str, erroneous: str) -> tuple[int, str, str]:
    """Return ``(offset, corrected_span, erroneous_span)`` for one minimal edit."""
    prefix = 0
    shared = min(len(corrected), len(erroneous))
    while prefix < shared and corrected[prefix] == erroneous[prefix]:
        prefix += 1

    suffix = 0
    remaining = min(len(corrected) - prefix, len(erroneous) - prefix)
    while (suffix < remaining and
           corrected[len(corrected) - suffix - 1] ==
           erroneous[len(erroneous) - suffix - 1]):
        suffix += 1

    corrected_end = len(corrected) - suffix if suffix else len(corrected)
    erroneous_end = len(erroneous) - suffix if suffix else len(erroneous)
    return prefix, corrected[prefix:corrected_end], erroneous[prefix:erroneous_end]


def lex_tokens(source: str) -> list[LexToken]:
    """Tokenize code while excluding whitespace, comments and string literals."""
    mask = code_mask(source)
    tokens: list[LexToken] = []
    for match in _TOKEN_RE.finditer(source):
        start, end = match.span()
        if not all(mask[start:end]):
            continue
        text = match.group(0)
        if re.fullmatch(r"[A-Za-z_]\w*", text):
            pattern = text if text in _KEYWORDS or text.startswith("__") else "<ID>"
        elif re.fullmatch(r"(?:0[xX][0-9A-Fa-f]+|\d+(?:\.\d*)?)", text):
            pattern = "<NUM>"
        else:
            pattern = text
        tokens.append(LexToken(text, start, end, pattern))
    return tokens


def build_token_index(tokens: Iterable[LexToken]) -> dict[str, tuple[int, ...]]:
    """Index normalized token patterns for fast multi-recipe replay."""
    positions: dict[str, list[int]] = {}
    for index, token in enumerate(tokens):
        positions.setdefault(token.pattern, []).append(index)
    return {pattern: tuple(values) for pattern, values in positions.items()}


def _new_text_is_portable(text: str) -> bool:
    if not text:
        return True
    mask = code_mask(text)
    # Comments and string/character literals deliberately do not become fixed
    # replay payloads.  Whitespace in them is harmless; any other masked byte is not.
    if any(not keep and not char.isspace() for char, keep in zip(text, mask)):
        return False
    for token in lex_tokens(text):
        if token.pattern == "<ID>":
            return False
    return True


def _edit_is_token_aligned(
    tokens: list[LexToken], start: int, old_text: str,
) -> tuple[bool, tuple[str, ...]]:
    end = start + len(old_text)
    if not old_text:
        inside = any(token.start < start < token.end for token in tokens)
        return not inside, ()
    edited = [token for token in tokens
              if token.end > start and token.start < end]
    if not edited:
        return False, ()
    aligned = edited[0].start == start and edited[-1].end == end
    return aligned, tuple(token.pattern for token in edited)


def extract_recipe(
    record: Record, *, context_tokens: int = 2,
) -> Optional[LearnedRecipe]:
    """Extract one lexical recipe from a verified paired Record."""
    if record.corrected_src is None or record.primary_diagnostic is None:
        return None
    diag_name = record.primary_diagnostic.diag_name
    if not diag_name:
        return None
    start, old_text, new_text = minimal_edit(
        record.corrected_src, record.erroneous_src
    )
    if not old_text and not new_text:
        return None
    tokens = lex_tokens(record.corrected_src)
    aligned, old_patterns = _edit_is_token_aligned(tokens, start, old_text)
    end = start + len(old_text)
    left = [token.pattern for token in tokens if token.end <= start]
    right = [token.pattern for token in tokens if token.start >= end]
    left_context = tuple(left[-context_tokens:])
    right_context = tuple(right[:context_tokens])
    portable = bool(
        aligned and (left_context or right_context or old_patterns)
        and _new_text_is_portable(new_text)
    )
    operation = "insert" if not old_text else ("delete" if not new_text else "replace")
    identity = (
        diag_name, record.language, operation, old_patterns, new_text,
        left_context, right_context, portable,
    )
    encoded = json.dumps(identity, sort_keys=True).encode()
    recipe_id = "recipe-" + hashlib.sha256(encoded).hexdigest()[:12]
    return LearnedRecipe(
        recipe_id=recipe_id,
        diag_name=diag_name,
        language=record.language,
        operation=operation,
        old_patterns=old_patterns,
        new_text=new_text,
        left_context=left_context,
        right_context=right_context,
        portable=portable,
        exemplar_ids=(record.record_id,),
    )


def extract_recipes(
    records: Iterable[Record], *, context_tokens: int = 2,
) -> list[LearnedRecipe]:
    """Extract and aggregate identical diagnostic-specific lexical recipes."""
    grouped: dict[tuple, LearnedRecipe] = {}
    for record in records:
        recipe = extract_recipe(record, context_tokens=context_tokens)
        if recipe is None:
            continue
        key = recipe.identity()
        if key not in grouped:
            grouped[key] = recipe
            continue
        current = grouped[key]
        grouped[key] = replace(
            current,
            support=current.support + 1,
            exemplar_ids=current.exemplar_ids + recipe.exemplar_ids,
        )
    return sorted(
        grouped.values(),
        key=lambda recipe: (
            not recipe.portable, -recipe.support, recipe.diag_name,
            recipe.recipe_id,
        ),
    )


def _matches(actual: list[LexToken], start: int, patterns: tuple[str, ...]) -> bool:
    if start < 0 or start + len(patterns) > len(actual):
        return False
    return all(actual[start + offset].pattern == pattern
               for offset, pattern in enumerate(patterns))


def _candidate_edit_indices(
    tokens: list[LexToken], recipe: LearnedRecipe,
    token_index: dict[str, tuple[int, ...]],
) -> Iterable[int]:
    middle = () if recipe.operation == "insert" else recipe.old_patterns
    sequence = recipe.left_context + middle + recipe.right_context
    anchors = [
        (offset, pattern, token_index.get(pattern, ()))
        for offset, pattern in enumerate(sequence)
        if pattern not in ("<ID>", "<NUM>")
    ]
    if not anchors:
        upper = len(tokens) + 1 if recipe.operation == "insert" else len(tokens)
        return range(upper)
    anchor_offset, _pattern, positions = min(anchors, key=lambda item: len(item[2]))
    edit_offset = len(recipe.left_context)
    return sorted({position - anchor_offset + edit_offset for position in positions})


def apply_recipe(
    source: str,
    recipe: LearnedRecipe,
    *,
    max_candidates: int = 8,
    tokens: Optional[list[LexToken]] = None,
    token_index: Optional[dict[str, tuple[int, ...]]] = None,
) -> list[RecipeApplication]:
    """Replay a portable recipe at lexically compatible sites in ``source``."""
    if not recipe.portable or max_candidates <= 0:
        return []
    tokens = tokens if tokens is not None else lex_tokens(source)
    token_index = token_index if token_index is not None else build_token_index(tokens)
    candidates = _candidate_edit_indices(tokens, recipe, token_index)
    applications: list[RecipeApplication] = []
    seen_spans: set[tuple[int, int]] = set()

    if recipe.operation == "insert":
        # Boundary i sits between tokens i-1 and i.
        for i in candidates:
            if not _matches(tokens, i - len(recipe.left_context),
                            recipe.left_context):
                continue
            if not _matches(tokens, i, recipe.right_context):
                continue
            if i < len(tokens):
                start = tokens[i].start
            elif tokens:
                start = tokens[-1].end
            else:
                continue
            span = (start, start)
            if span in seen_spans:
                continue
            seen_spans.add(span)
            applications.append(RecipeApplication(
                src=source[:start] + recipe.new_text + source[start:],
                start=start,
                end=start,
                replacement=recipe.new_text,
                recipe_id=recipe.recipe_id,
            ))
            if len(applications) >= max_candidates:
                break
        return applications

    width = len(recipe.old_patterns)
    if width == 0:
        return []
    for i in candidates:
        if not _matches(tokens, i, recipe.old_patterns):
            continue
        if not _matches(tokens, i - len(recipe.left_context), recipe.left_context):
            continue
        if not _matches(tokens, i + width, recipe.right_context):
            continue
        start, end = tokens[i].start, tokens[i + width - 1].end
        span = (start, end)
        if span in seen_spans:
            continue
        seen_spans.add(span)
        applications.append(RecipeApplication(
            src=source[:start] + recipe.new_text + source[end:],
            start=start,
            end=end,
            replacement=recipe.new_text,
            recipe_id=recipe.recipe_id,
        ))
        if len(applications) >= max_candidates:
            break
    return applications
