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
    kind: str


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
    replacement_parts: tuple[tuple[str, str], ...] = ()
    support: int = 1
    exemplar_ids: tuple[str, ...] = ()

    def identity(self) -> tuple:
        return (
            self.diag_name, self.language, self.operation, self.old_patterns,
            self.new_text, self.left_context, self.right_context, self.portable,
            self.replacement_parts,
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
            "replacement_parts": [list(part) for part in self.replacement_parts],
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
            replacement_parts=tuple(
                tuple(part) for part in value.get(
                    "replacement_parts", (("literal", value.get("new_text", "")),)
                )
            ),
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
            if text in _KEYWORDS or text.startswith("__"):
                pattern, kind = text, "exact"
            else:
                pattern, kind = "<ID>", "id"
        elif re.fullmatch(r"(?:0[xX][0-9A-Fa-f]+|\d+(?:\.\d*)?)", text):
            pattern, kind = "<NUM>", "num"
        else:
            pattern, kind = text, "exact"
        tokens.append(LexToken(text, start, end, pattern, kind))
    return tokens


def build_token_index(tokens: Iterable[LexToken]) -> dict[str, tuple[int, ...]]:
    """Index normalized token patterns for fast multi-recipe replay."""
    positions: dict[str, list[int]] = {}
    for index, token in enumerate(tokens):
        positions.setdefault(token.pattern, []).append(index)
    return {pattern: tuple(values) for pattern, values in positions.items()}


def _replacement_template(
    text: str,
    identifier_labels: dict[str, str],
    *,
    allow_fresh_identifiers: bool = False,
    allow_literal_payloads: bool = False,
    preserve_inserted_identifier_spellings: bool = False,
) -> tuple[tuple[tuple[str, str], ...], bool]:
    if not text:
        return (), True
    mask = code_mask(text)
    # Comments and string/character literals deliberately do not become fixed
    # replay payloads.  Whitespace in them is harmless; any other masked byte is not.
    if (not allow_literal_payloads and any(
        not keep and not char.isspace() for char, keep in zip(text, mask)
    )):
        return (("literal", text),), False
    parts: list[tuple[str, str]] = []
    fresh_labels: dict[str, str] = {}
    cursor = 0
    for token in lex_tokens(text):
        if token.kind != "id":
            continue
        label = identifier_labels.get(token.text)
        if label is None:
            if preserve_inserted_identifier_spellings:
                label = token.text
                kind = "literal"
            elif not allow_fresh_identifiers:
                return (("literal", text),), False
            else:
                label = fresh_labels.setdefault(
                    token.text, f"FRESH{len(fresh_labels)}"
                )
                kind = "fresh"
        else:
            kind = "binding"
        if token.start > cursor:
            parts.append(("literal", text[cursor:token.start]))
        parts.append((kind, label))
        cursor = token.end
    if cursor < len(text):
        parts.append(("literal", text[cursor:]))
    if not parts:
        parts.append(("literal", text))
    return tuple(parts), True


def _normalize_edit_to_token_span(
    corrected: str,
    erroneous: str,
    tokens: list[LexToken],
    start: int,
    old_text: str,
    new_text: str,
) -> tuple[int, str, str]:
    """Expand an intra-token character edit to one complete token span.

    The expansion is accepted only when the reconstructed erroneous source is
    byte-identical to the original pair.  Edits that begin or end in
    whitespace between tokens remain unchanged because the token replay engine
    cannot represent those boundaries faithfully.
    """

    end = start + len(old_text)
    if old_text:
        edited = [
            token for token in tokens
            if token.end > start and token.start < end
        ]
        if not edited:
            return start, old_text, new_text
        expanded_start = edited[0].start
        expanded_end = edited[-1].end
        if expanded_start > start:
            # A minimal diff can begin in whitespace that is removed together
            # with the first edited token.  Absorb the preceding token so the
            # replay span is token-aligned while still reproducing the pair
            # byte-for-byte.
            if not corrected[start:expanded_start].isspace():
                return start, old_text, new_text
            previous = next(
                (token for token in reversed(tokens) if token.end <= start),
                None,
            )
            if previous is None:
                return start, old_text, new_text
            expanded_start = previous.start
        if expanded_end < end:
            # Symmetrically absorb the following token when the minimal diff
            # ends in inter-token whitespace.
            if not corrected[expanded_end:end].isspace():
                return start, old_text, new_text
            following = next(
                (token for token in tokens if token.start >= end),
                None,
            )
            if following is None:
                return start, old_text, new_text
            expanded_end = following.end
    else:
        enclosing = next(
            (token for token in tokens if token.start < start < token.end),
            None,
        )
        if enclosing is None:
            return start, old_text, new_text
        expanded_start, expanded_end = enclosing.start, enclosing.end

    expanded_old = corrected[expanded_start:expanded_end]
    expanded_new = (
        corrected[expanded_start:start]
        + new_text
        + corrected[end:expanded_end]
    )
    rebuilt = (
        corrected[:expanded_start] + expanded_new + corrected[expanded_end:]
    )
    if rebuilt != erroneous:
        return start, old_text, new_text
    return expanded_start, expanded_old, expanded_new


def _edit_is_token_aligned(
    tokens: list[LexToken], start: int, old_text: str,
) -> tuple[bool, tuple[LexToken, ...]]:
    end = start + len(old_text)
    if not old_text:
        inside = any(token.start < start < token.end for token in tokens)
        return not inside, ()
    edited = [token for token in tokens
              if token.end > start and token.start < end]
    if not edited:
        return False, ()
    aligned = edited[0].start == start and edited[-1].end == end
    return aligned, tuple(edited)


def _bind_identifier_patterns(
    left: tuple[LexToken, ...], edited: tuple[LexToken, ...],
    right: tuple[LexToken, ...],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], dict[str, str]]:
    labels: dict[str, str] = {}

    def pattern(token: LexToken) -> str:
        if token.kind != "id":
            return token.pattern
        if token.text not in labels:
            labels[token.text] = f"ID{len(labels)}"
        return f"<{labels[token.text]}>"

    return (
        tuple(pattern(token) for token in left),
        tuple(pattern(token) for token in edited),
        tuple(pattern(token) for token in right),
        labels,
    )


def extract_recipe(
    record: Record,
    *,
    context_tokens: int = 2,
    max_edit_chars: int = 256,
    allow_fresh_identifiers: bool = False,
    allow_literal_payloads: bool = False,
    normalize_token_edits: bool = False,
    preserve_inserted_identifier_spellings: bool = False,
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
    aligned, edited_tokens = _edit_is_token_aligned(tokens, start, old_text)
    if normalize_token_edits and not aligned:
        start, old_text, new_text = _normalize_edit_to_token_span(
            record.corrected_src,
            record.erroneous_src,
            tokens,
            start,
            old_text,
            new_text,
        )
        aligned, edited_tokens = _edit_is_token_aligned(tokens, start, old_text)
    end = start + len(old_text)
    left_tokens = tuple(
        [token for token in tokens if token.end <= start][-context_tokens:]
    )
    right_tokens = tuple(
        [token for token in tokens if token.start >= end][:context_tokens]
    )
    left_context, old_patterns, right_context, identifier_labels = (
        _bind_identifier_patterns(left_tokens, edited_tokens, right_tokens)
    )
    replacement_parts, replacement_portable = _replacement_template(
        new_text,
        identifier_labels,
        allow_fresh_identifiers=allow_fresh_identifiers,
        allow_literal_payloads=allow_literal_payloads,
        preserve_inserted_identifier_spellings=(
            preserve_inserted_identifier_spellings
        ),
    )
    portable = bool(
        aligned and (left_context or right_context or old_patterns)
        and replacement_portable
        and len(old_text) <= max_edit_chars
        and len(new_text) <= max_edit_chars
    )
    operation = "insert" if not old_text else ("delete" if not new_text else "replace")
    identity = (
        diag_name, record.language, operation, old_patterns, new_text,
        left_context, right_context, portable, replacement_parts,
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
        replacement_parts=replacement_parts,
        exemplar_ids=(record.record_id,),
    )


def extract_recipes(
    records: Iterable[Record],
    *,
    context_tokens: int = 2,
    max_edit_chars: int = 256,
    allow_fresh_identifiers: bool = False,
    allow_literal_payloads: bool = False,
    normalize_token_edits: bool = False,
    preserve_inserted_identifier_spellings: bool = False,
) -> list[LearnedRecipe]:
    """Extract and aggregate identical diagnostic-specific lexical recipes."""
    grouped: dict[tuple, LearnedRecipe] = {}
    for record in records:
        recipe = extract_recipe(
            record,
            context_tokens=context_tokens,
            max_edit_chars=max_edit_chars,
            allow_fresh_identifiers=allow_fresh_identifiers,
            allow_literal_payloads=allow_literal_payloads,
            normalize_token_edits=normalize_token_edits,
            preserve_inserted_identifier_spellings=(
                preserve_inserted_identifier_spellings
            ),
        )
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


_BOUND_PATTERN_RE = re.compile(r"<(ID\d+)>")


def _match_sequence(
    actual: list[LexToken], start: int, patterns: tuple[str, ...],
) -> Optional[dict[str, str]]:
    if start < 0 or start + len(patterns) > len(actual):
        return None
    bindings: dict[str, str] = {}
    for offset, pattern in enumerate(patterns):
        token = actual[start + offset]
        bound = _BOUND_PATTERN_RE.fullmatch(pattern)
        if bound:
            if token.kind != "id":
                return None
            label = bound.group(1)
            if label in bindings and bindings[label] != token.text:
                return None
            bindings[label] = token.text
        elif pattern == "<ID>":
            if token.kind != "id":
                return None
        elif pattern == "<NUM>":
            if token.kind != "num":
                return None
        elif token.pattern != pattern:
            return None
    return bindings


def _is_placeholder(pattern: str) -> bool:
    return pattern in ("<ID>", "<NUM>") or bool(
        _BOUND_PATTERN_RE.fullmatch(pattern)
    )


def _render_replacement(
    recipe: LearnedRecipe,
    bindings: dict[str, str],
    used_identifiers: set[str],
) -> Optional[str]:
    parts = recipe.replacement_parts or (("literal", recipe.new_text),)
    rendered: list[str] = []
    fresh: dict[str, str] = {}

    def fresh_identifier(label: str) -> str:
        if label in fresh:
            return fresh[label]
        suffix = 0
        while True:
            candidate = "fuzzlang_tmp" if suffix == 0 else f"fuzzlang_tmp_{suffix}"
            if candidate not in used_identifiers and candidate not in fresh.values():
                fresh[label] = candidate
                return candidate
            suffix += 1

    for kind, value in parts:
        if kind == "literal":
            rendered.append(value)
        elif kind == "binding" and value in bindings:
            rendered.append(bindings[value])
        elif kind == "fresh" and re.fullmatch(r"FRESH\d+", value):
            rendered.append(fresh_identifier(value))
        else:
            return None
    return "".join(rendered)


def _candidate_edit_indices(
    tokens: list[LexToken], recipe: LearnedRecipe,
    token_index: dict[str, tuple[int, ...]],
) -> Iterable[int]:
    middle = () if recipe.operation == "insert" else recipe.old_patterns
    sequence = recipe.left_context + middle + recipe.right_context
    anchors = [
        (offset, pattern, token_index.get(pattern, ()))
        for offset, pattern in enumerate(sequence)
        if not _is_placeholder(pattern)
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
    used_identifiers = {token.text for token in tokens if token.kind == "id"}
    candidates = _candidate_edit_indices(tokens, recipe, token_index)
    applications: list[RecipeApplication] = []
    seen_spans: set[tuple[int, int]] = set()

    if recipe.operation == "insert":
        # Boundary i sits between tokens i-1 and i.
        for i in candidates:
            sequence = recipe.left_context + recipe.right_context
            bindings = _match_sequence(
                tokens, i - len(recipe.left_context), sequence
            )
            if bindings is None:
                continue
            replacement = _render_replacement(recipe, bindings, used_identifiers)
            if replacement is None:
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
                src=source[:start] + replacement + source[start:],
                start=start,
                end=start,
                replacement=replacement,
                recipe_id=recipe.recipe_id,
            ))
            if len(applications) >= max_candidates:
                break
        return applications

    width = len(recipe.old_patterns)
    if width == 0:
        return []
    for i in candidates:
        sequence = (
            recipe.left_context + recipe.old_patterns + recipe.right_context
        )
        bindings = _match_sequence(
            tokens, i - len(recipe.left_context), sequence
        )
        if bindings is None:
            continue
        replacement = _render_replacement(recipe, bindings, used_identifiers)
        if replacement is None:
            continue
        start, end = tokens[i].start, tokens[i + width - 1].end
        span = (start, end)
        if span in seen_spans:
            continue
        seen_spans.add(span)
        applications.append(RecipeApplication(
            src=source[:start] + replacement + source[end:],
            start=start,
            end=end,
            replacement=replacement,
            recipe_id=recipe.recipe_id,
        ))
        if len(applications) >= max_candidates:
            break
    return applications
