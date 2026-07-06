# Real-code error injection (`gen/realcorpus/`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a target-first (diagnostic-driven) pipeline that injects a chosen compile error into a real LLVM translation unit and emits a verified repair instance, producing an eval slice in `run_sweep` input format.

**Architecture:** Drive the in-scope diagnostic catalog (inducibility-priority). For each target diagnostic A: rank real code fragments by feature relevance, ask `gpt-5.4-mini` (primed with A's exemplar trigger from the existing dataset) for a minimal localized edit that triggers A, apply it, verify with the real per-file compile command, and emit a `Record` tagged with `cascade_size` and `primary_matches_target`. Reuses the existing verifier, record schema, catalog, and compile-command machinery.

**Tech Stack:** Python 3 (src layout, `PYTHONPATH=src`), pytest, patched clang 22.1.8 (`FuzzlangClangVerifier`), OpenAI `gpt-5.4-mini` via `repair.agent.chat_backend`.

**Design spec:** `docs/superpowers/specs/2026-07-05-realcorpus-error-injection-design.md`

---

## Conventions for every task

- Tests run with: `PYTHONPATH=src /usr/tce/bin/python3 -m pytest <path> -q` (this interpreter has pytest + openai; the default `python3` does not).
- Patched clang / diagtool (only for the integration tasks 12–13):
  `export FUZZLANG_CLANG_BIN=/p/lustre2/shan4/fuzzlang-clang/bin/clang`
  `export FUZZLANG_DIAGTOOL_BIN=/p/lustre2/shan4/fuzzlang-clang/bin/diagtool`
- Commit messages: **no "Claude"/Co-Authored-By**. Plain conventional-commit style.
- Follow existing repo style: `from __future__ import annotations`, module docstrings, small focused files.

## File structure

| file | responsibility |
|---|---|
| `src/foundation/compile_db.py` | parse `compile_commands.json`; portable-ize a recorded command (extracted from `real/`) |
| `src/foundation/tests/test_compile_db.py` | unit tests for the above |
| `src/real/reproduce_stage2_llvm.py` (modify) | import the extracted helpers instead of its private copies |
| `src/gen/realcorpus/__init__.py` | package marker |
| `src/gen/realcorpus/region.py` | split a source into candidate function spans |
| `src/gen/realcorpus/features.py` | syntactic feature tags for fragments and targets |
| `src/gen/realcorpus/corpus.py` | `Fragment` + build the feature-indexed fragment pool from clean TUs |
| `src/gen/realcorpus/targets.py` | `Target` + ordered target list + exemplar priming |
| `src/gen/realcorpus/select.py` | rank fragments for a target by feature overlap |
| `src/gen/realcorpus/prompt.py` | `Edit` + build injection messages + parse the reply |
| `src/gen/realcorpus/inject.py` | apply an edit; one model call → erroneous source |
| `src/gen/realcorpus/collect.py` | verify + emit a `Record` (cascade size, target match) |
| `src/gen/realcorpus/run_realcorpus.py` | CLI driver → eval JSONL (`run_sweep` format) |
| `src/gen/realcorpus/tests/*` | tests per module |

---

## Task 1: Confirm the compile DB is usable (no code)

**Files:** none (verification only).

- [ ] **Step 1: Assert the DB is the pinned 22.1.8 tree and patched clang clean-compiles a sample TU**

Run:
```bash
cd /p/lustre2/shan4/new-fuzzlang
export FUZZLANG_CLANG_BIN=/p/lustre2/shan4/fuzzlang-clang/bin/clang
CCDB=/p/lustre2/shan4/fuzzlang-llvm-build/compile_commands.json
PYTHONPATH=src /usr/tce/bin/python3 - "$CCDB" <<'PY'
import json,sys,shlex,subprocess,tempfile,os
rows=json.load(open(sys.argv[1]))
# pick a small TU
rows=[r for r in rows if r["file"].endswith((".cpp",".cc",".c"))]
rows.sort(key=lambda r: os.path.getsize(r["file"]) if os.path.exists(r["file"]) else 1e9)
e=rows[0]
assert "external/llvm-project" in e["file"], "DB not built from pinned submodule!"
toks=shlex.split(e["command"]) if "command" in e else e["arguments"]
# swap compiler, drop -o + source, force -fsyntax-only
clang=os.environ["FUZZLANG_CLANG_BIN"]
out=[clang]; skip=False
srcabs=os.path.realpath(e["file"])
for t in toks[1:]:
    if skip: skip=False; continue
    if t=="-o": skip=True; continue
    if t.startswith("-o"): continue
    if os.path.realpath(t)==srcabs: continue
    out.append(t)
out += ["-fsyntax-only","-fno-color-diagnostics", e["file"]]
r=subprocess.run(out, capture_output=True, text=True, errors="replace", timeout=120)
print("sample TU:", e["file"])
print("clean-compile rc:", r.returncode)
print(r.stderr[-500:] if r.returncode else "OK (compiles clean)")
PY
```
Expected: `DB not built from pinned submodule!` does NOT fire; `clean-compile rc: 0` for at least this small TU (if not, try the next few — some TUs use g++-only flags; that is expected yield loss, not a blocker).

- [ ] **Step 2: Note the outcome**

If most sampled TUs clean-compile, proceed. If nearly all fail on flag incompatibility, the plan's `sanitize_cmd` (Task 5) mitigates by stripping `-Werror`; if they still fail, stop and revisit the spec's compile-env section.

---

## Task 2: Extract `foundation/compile_db.py`

**Files:**
- Create: `src/foundation/compile_db.py`
- Create: `src/foundation/tests/test_compile_db.py`
- Modify: `src/real/reproduce_stage2_llvm.py` (replace private helpers with imports)

- [ ] **Step 1: Write the failing test**

Create `src/foundation/tests/test_compile_db.py`:
```python
"""Tests for compile_commands.json handling shared by real/ and gen/realcorpus."""
from __future__ import annotations

import json
from pathlib import Path

from foundation.compile_db import build_clang_argv, load_compile_db, split_command


def test_load_compile_db_indexes_by_realpath(tmp_path: Path):
    ccdb = tmp_path / "compile_commands.json"
    ccdb.write_text(json.dumps([
        {"directory": "/b", "file": "/src/a.cpp", "command": "g++ -c /src/a.cpp -o a.o"},
    ]))
    db = load_compile_db(ccdb)
    assert "/src/a.cpp" in db


def test_split_command_handles_command_and_arguments():
    assert split_command({"command": "g++ -c a.cpp"}) == ["g++", "-c", "a.cpp"]
    assert split_command({"arguments": ["g++", "-c", "a.cpp"]}) == ["g++", "-c", "a.cpp"]


def test_build_clang_argv_portable_placeholders():
    entry = {"directory": "/b", "file": "/src/a.cpp",
             "command": "g++ -std=c++17 -I/inc -c /src/a.cpp -o /b/a.o"}
    argv = build_clang_argv(entry, "__CLANG__", "__SRC__")
    assert argv[0] == "__CLANG__"
    assert "-o" not in argv and "/b/a.o" not in argv
    assert "/src/a.cpp" not in argv           # recorded source dropped
    assert argv[-1] == "__SRC__"              # our source appended last
    assert "-fsyntax-only" in argv and "-fno-color-diagnostics" in argv
    assert "-std=c++17" in argv and "-I/inc" in argv
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src /usr/tce/bin/python3 -m pytest src/foundation/tests/test_compile_db.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'foundation.compile_db'`

- [ ] **Step 3: Create `src/foundation/compile_db.py`**

```python
"""Parse compile_commands.json and turn a recorded compile command into a
portable, verifier-runnable form. Shared by `real/` (real-error reproduction)
and `gen/realcorpus/` (real-code error injection).

`build_clang_argv` replaces the compiler with a placeholder, drops `-o`, strips
the recorded source path, forces `-fsyntax-only -fno-color-diagnostics`, and
appends a source placeholder — yielding the `[__CLANG__ ... __SRC__]` shape the
FuzzlangClangVerifier substitutes.
"""
from __future__ import annotations

import json
import os
import shlex
from pathlib import Path


def load_compile_db(ccdb_path: Path) -> dict[str, dict]:
    """Index compile_commands.json by absolute (realpath) source file."""
    with Path(ccdb_path).open() as f:
        rows = json.load(f)
    index: dict[str, dict] = {}
    for r in rows:
        fpath = os.path.realpath(
            r["file"] if os.path.isabs(r["file"])
            else os.path.join(r.get("directory", ""), r["file"])
        )
        index[fpath] = r
    return index


def split_command(entry: dict) -> list[str]:
    """Return the argv list from a `command` (string) or `arguments` (list) entry."""
    if "arguments" in entry:
        return list(entry["arguments"])
    return shlex.split(entry["command"])


def build_clang_argv(entry: dict, clang_bin: str, src: str) -> list[str]:
    """Portable-ize a recorded compile command for buggy/injected source.

    - Replace the compiler (argv[0]) with `clang_bin`.
    - Drop `-o <out>`.
    - Drop the recorded source path.
    - Force `-fsyntax-only` and `-fno-color-diagnostics`.
    - Append `src` as the (only) source argument.
    """
    argv = split_command(entry)
    argv[0] = clang_bin
    entry_file = os.path.realpath(
        entry["file"] if os.path.isabs(entry["file"])
        else os.path.join(entry.get("directory", ""), entry["file"])
    )
    out: list[str] = [clang_bin]
    skip_next = False
    for tok in argv[1:]:
        if skip_next:
            skip_next = False
            continue
        if tok == "-o":
            skip_next = True
            continue
        if tok.startswith("-o"):
            continue
        if os.path.realpath(tok) == entry_file:
            continue
        out.append(tok)
    if "-fsyntax-only" not in out:
        out.append("-fsyntax-only")
    if "-fno-color-diagnostics" not in out:
        out.append("-fno-color-diagnostics")
    out.append(src)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src /usr/tce/bin/python3 -m pytest src/foundation/tests/test_compile_db.py -q`
Expected: PASS (3 tests)

- [ ] **Step 5: Refactor `real/reproduce_stage2_llvm.py` to use the shared module**

In `src/real/reproduce_stage2_llvm.py`, add near the top imports:
```python
from foundation.compile_db import build_clang_argv as _shared_build_clang_argv
from foundation.compile_db import load_compile_db as _shared_load_compile_db
from foundation.compile_db import split_command as _shared_split_command
```
Then replace the *bodies* of the existing `_load_compile_db`, `_split_command`, and `_build_clang_argv` with thin delegations (keep the names/signatures so the rest of the file and its tests are unchanged):
```python
def _load_compile_db(ccdb_path: Path) -> dict[str, dict]:
    return _shared_load_compile_db(ccdb_path)

def _split_command(entry: dict) -> list[str]:
    return _shared_split_command(entry)

def _build_clang_argv(entry: dict, clang_bin: str, src_tmpfile: str) -> list[str]:
    return _shared_build_clang_argv(entry, clang_bin, src_tmpfile)
```

- [ ] **Step 6: Run the real/ tests to confirm no regression**

Run: `PYTHONPATH=src /usr/tce/bin/python3 -m pytest src/real -q`
Expected: PASS (unchanged behavior)

- [ ] **Step 7: Commit**

```bash
git add src/foundation/compile_db.py src/foundation/tests/test_compile_db.py src/real/reproduce_stage2_llvm.py
git commit -m "foundation: extract shared compile_db helpers from real/"
```

---

## Task 3: `region.py` — function-span selection

**Files:**
- Create: `src/gen/realcorpus/__init__.py` (empty)
- Create: `src/gen/realcorpus/region.py`
- Create: `src/gen/realcorpus/tests/__init__.py` (empty)
- Create: `src/gen/realcorpus/tests/test_region.py`

- [ ] **Step 1: Write the failing test**

Create `src/gen/realcorpus/tests/test_region.py`:
```python
from __future__ import annotations

from gen.realcorpus.region import select_regions

SRC = """\
#include <x>
int add(int a, int b) {
    int s = a + b;
    return s;
}
// a comment with { braces } that must be ignored
int mul(int a, int b) {
    return a * b;
}
"""


def test_select_regions_finds_function_bodies():
    spans = select_regions(SRC, max_regions=8, min_lines=2)
    texts = [SRC[a:b] for a, b in spans]
    assert any("int s = a + b;" in t for t in texts)
    assert any("return a * b;" in t for t in texts)


def test_regions_are_within_bounds_and_ordered():
    spans = select_regions(SRC)
    assert all(0 <= a < b <= len(SRC) for a, b in spans)
    assert spans == sorted(spans)


def test_braces_in_comments_do_not_start_a_region():
    src = "// just { a comment }\nint f(){ return 0; }\n"
    spans = select_regions(src, min_lines=0)
    assert len(spans) == 1
    assert "return 0;" in src[spans[0][0]:spans[0][1]]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src /usr/tce/bin/python3 -m pytest src/gen/realcorpus/tests/test_region.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create `src/gen/realcorpus/region.py`**

```python
"""Split a C/C++ source into candidate editable spans (function bodies).

A span runs from a function's signature start to the matching close brace of its
body. Braces inside comments/strings are ignored via the shared code mask. Pure
text — no libclang. Good enough to give the injector a bounded, meaningful
region to edit.
"""
from __future__ import annotations

from gen.mutate._scan import code_mask


def select_regions(src: str, *, max_regions: int = 8,
                   min_lines: int = 2) -> list[tuple[int, int]]:
    """Return up to `max_regions` (start, end) char spans of function bodies.

    Heuristic: find a code `{` whose nearest preceding non-space code char is
    `)` (a function/ctor body opener), then match to its `}`. The span starts at
    the line containing the signature and ends just after the close brace.
    """
    mask = code_mask(src)
    spans: list[tuple[int, int]] = []
    n = len(src)
    i = 0
    while i < n and len(spans) < max_regions:
        if mask[i] and src[i] == "{" and _preceded_by_paren(src, mask, i):
            close = _match_brace(src, mask, i)
            if close is not None:
                start = src.rfind("\n", 0, i) + 1  # start of the signature line
                end = close + 1
                if src.count("\n", start, end) >= min_lines:
                    spans.append((start, end))
                    i = end
                    continue
        i += 1
    return spans


def _preceded_by_paren(src: str, mask: list[bool], brace: int) -> bool:
    j = brace - 1
    while j >= 0:
        if not mask[j] or src[j].isspace():
            j -= 1
            continue
        return src[j] == ")"
    return False


def _match_brace(src: str, mask: list[bool], open_idx: int) -> int | None:
    depth = 0
    for k in range(open_idx, len(src)):
        if not mask[k]:
            continue
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return k
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src /usr/tce/bin/python3 -m pytest src/gen/realcorpus/tests/test_region.py -q`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/gen/realcorpus/__init__.py src/gen/realcorpus/region.py src/gen/realcorpus/tests/__init__.py src/gen/realcorpus/tests/test_region.py
git commit -m "gen(realcorpus): function-span region selection"
```

---

## Task 4: `features.py` — syntactic feature tags

**Files:**
- Create: `src/gen/realcorpus/features.py`
- Create: `src/gen/realcorpus/tests/test_features.py`

- [ ] **Step 1: Write the failing test**

Create `src/gen/realcorpus/tests/test_features.py`:
```python
from __future__ import annotations

from gen.realcorpus.features import fragment_features, target_features


def test_fragment_features_detects_constructs():
    f = fragment_features("template <class T> T f(T* p) { return p->g(); }")
    assert "template" in f
    assert "pointer" in f
    assert "member" in f       # -> access


def test_fragment_features_detects_call_and_class():
    f = fragment_features("struct S { int x; }; int main(){ return foo(1); }")
    assert "call" in f
    assert "class" in f


def test_target_features_maps_diagnostic_name():
    assert "call" in target_features("err_ovl_no_viable_function_in_call", "no matching function")
    assert "template" in target_features("err_template_arg_list", "template argument")
    assert "member" in target_features("err_no_member", "no member named 'x'")


def test_target_features_empty_for_generic_name():
    # A syntactic diagnostic maps to no structural feature (matches any fragment).
    assert target_features("err_expected_semi_declaration", "expected ';'") == frozenset()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src /usr/tce/bin/python3 -m pytest src/gen/realcorpus/tests/test_features.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create `src/gen/realcorpus/features.py`**

```python
"""Cheap syntactic feature tags shared vocabulary. Used to rank real fragments
against a target diagnostic so the injector is tried on plausibly-inducible
fragments first. Heuristic and deliberately small.
"""
from __future__ import annotations

import re

FEATURE_VOCAB = (
    "template", "call", "pointer", "member", "class", "constexpr",
    "enum", "cast", "lambda", "operator", "virtual", "reference",
)

# fragment-side detectors: feature -> regex on the code text.
_FRAG_PATTERNS = {
    "template": re.compile(r"\btemplate\s*<"),
    "call": re.compile(r"\w\s*\("),
    "pointer": re.compile(r"[\w>]\s*\*\s*\w|->"),
    "member": re.compile(r"->|\.\w|::"),
    "class": re.compile(r"\b(class|struct)\b"),
    "constexpr": re.compile(r"\bconstexpr\b"),
    "enum": re.compile(r"\benum\b"),
    "cast": re.compile(r"\b(static_cast|reinterpret_cast|const_cast|dynamic_cast)\b"),
    "lambda": re.compile(r"\]\s*\("),
    "operator": re.compile(r"\boperator\b"),
    "virtual": re.compile(r"\bvirtual\b"),
    "reference": re.compile(r"[\w>]\s*&\s*\w"),
}

# target-side keyword hints: feature -> substrings that may appear in a
# diagnostic name or message.
_TARGET_HINTS = {
    "template": ("template", "instantiat", "typename"),
    "call": ("call", "ovl", "argument", "function", "overload"),
    "pointer": ("pointer", "deref", "nullptr", "indirection"),
    "member": ("member", "->", "field", "base class"),
    "class": ("class", "struct", "abstract", "incomplete type"),
    "constexpr": ("constexpr", "constant expression", "consteval"),
    "enum": ("enum", "enumerator"),
    "cast": ("cast", "conversion", "convert"),
    "lambda": ("lambda", "capture"),
    "operator": ("operator",),
    "virtual": ("virtual", "override", "pure"),
    "reference": ("reference", "bind"),
}


def fragment_features(text: str) -> frozenset[str]:
    return frozenset(f for f, pat in _FRAG_PATTERNS.items() if pat.search(text))


def target_features(name: str, message: str) -> frozenset[str]:
    blob = f"{name} {message}".lower()
    return frozenset(f for f, hints in _TARGET_HINTS.items()
                     if any(h in blob for h in hints))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src /usr/tce/bin/python3 -m pytest src/gen/realcorpus/tests/test_features.py -q`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/gen/realcorpus/features.py src/gen/realcorpus/tests/test_features.py
git commit -m "gen(realcorpus): syntactic feature tags for fragments and targets"
```

---

## Task 5: `corpus.py` — `Fragment` + fragment-index builder

**Files:**
- Create: `src/gen/realcorpus/corpus.py`
- Create: `src/gen/realcorpus/tests/test_corpus.py`

- [ ] **Step 1: Write the failing test**

Create `src/gen/realcorpus/tests/test_corpus.py`:
```python
from __future__ import annotations

import json
from pathlib import Path

from foundation.types import DiagInfo, VerifierResult
from foundation.verifier.mock import MockVerifier, ok_result
from gen.realcorpus.corpus import Fragment, build_fragment_index, sanitize_cmd


def test_sanitize_cmd_drops_werror_only():
    cmd = ["__CLANG__", "-Werror", "-Werror=return-type", "-Wall", "-std=c++17", "__SRC__"]
    out = sanitize_cmd(cmd)
    assert "-Werror" not in out and "-Werror=return-type" not in out
    assert "-Wall" in out and "-std=c++17" in out


def _write_tu(tmp_path: Path, name: str, body: str) -> str:
    p = tmp_path / name
    p.write_text(body)
    return str(p)


def test_build_fragment_index_keeps_only_clean_tus(tmp_path: Path):
    good = _write_tu(tmp_path, "good.cpp", "int add(int a,int b){ return a+b; }\n")
    bad = _write_tu(tmp_path, "bad.cpp", "int oops(int a){ return a\n}\n")
    ccdb = tmp_path / "compile_commands.json"
    ccdb.write_text(json.dumps([
        {"directory": str(tmp_path), "file": good, "command": f"g++ -c {good}"},
        {"directory": str(tmp_path), "file": bad, "command": f"g++ -c {bad}"},
    ]))
    from foundation.compile_db import load_compile_db
    db = load_compile_db(ccdb)

    def policy(src, cmd, logical_path):
        # "good" body compiles; "bad" (missing ;) errors.
        if "return a\n" in src:
            return VerifierResult(ok=False, diag=DiagInfo(
                diag_id=1, diag_name="err_expected_semi", diag_msg="expected ';'",
                file=logical_path, line=1, col=1, start_byte=0, end_byte=1,
                span_snippet="x"), raw_stderr="error: expected ';'")
        return ok_result()

    frags = build_fragment_index(db, MockVerifier(policy),
                                 n_files=10, seed=0, max_regions_per_file=4)
    paths = {f.rel_path for f in frags}
    assert any("good.cpp" in p for p in paths)
    assert not any("bad.cpp" in p for p in paths)
    # a fragment carries its region text and a placeholdered compile cmd
    f = next(iter(frags))
    assert f.compile_cmd[0] == "__CLANG__" and f.compile_cmd[-1] == "__SRC__"
    assert f.region_text in f.tu_src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src /usr/tce/bin/python3 -m pytest src/gen/realcorpus/tests/test_corpus.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create `src/gen/realcorpus/corpus.py`**

```python
"""Build a feature-indexed pool of real code fragments.

Each fragment is a function span from a real LLVM TU that compiles CLEAN under
its own (patched-clang) compile command — the correct-code invariant at the TU
level. Fragments carry their placeholdered compile command so a later injected
mutant can be verified with the exact real flags.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

from foundation.compile_db import build_clang_argv
from foundation.verifier.base import BaseVerifier
from gen.realcorpus.features import fragment_features
from gen.realcorpus.region import select_regions

_SRC_EXTS = (".c", ".cc", ".cpp", ".cxx", ".c++")


@dataclass(frozen=True)
class Fragment:
    rel_path: str                 # source path (as recorded in the compile DB)
    tu_src: str                   # full translation-unit text
    span: tuple[int, int]         # (start, end) char offsets of the region in tu_src
    features: frozenset[str]
    compile_cmd: list[str]        # placeholdered: [__CLANG__ ... __SRC__]

    @property
    def region_text(self) -> str:
        return self.tu_src[self.span[0]:self.span[1]]


def sanitize_cmd(cmd: list[str]) -> list[str]:
    """Drop -Werror flags so a TU that merely *warns* under clang still counts as
    clean. Everything else (incl. -Wall, -std, -I) is preserved."""
    return [t for t in cmd if not t.startswith("-Werror")]


def build_fragment_index(
    db: dict[str, dict],
    verifier: BaseVerifier,
    *,
    n_files: int,
    seed: int,
    max_regions_per_file: int = 6,
    min_region_lines: int = 3,
) -> list[Fragment]:
    """Sample up to `n_files` C/C++ TUs, keep those that compile clean under the
    patched clang, and emit one Fragment per selected function span."""
    files = [f for f in db if f.lower().endswith(_SRC_EXTS)]
    rng = random.Random(seed)
    rng.shuffle(files)

    frags: list[Fragment] = []
    scanned = 0
    for abs_path in files:
        if scanned >= n_files:
            break
        entry = db[abs_path]
        try:
            tu_src = Path(abs_path).read_text(errors="replace")
        except OSError:
            continue
        scanned += 1
        cmd = sanitize_cmd(build_clang_argv(entry, "__CLANG__", "__SRC__"))
        base = verifier.verify(tu_src, cmd, logical_path=abs_path)
        if not base.ok:
            continue  # correct-code invariant: TU must compile clean
        for span in select_regions(tu_src, max_regions=max_regions_per_file,
                                   min_lines=min_region_lines):
            frags.append(Fragment(
                rel_path=entry["file"], tu_src=tu_src, span=span,
                features=fragment_features(tu_src[span[0]:span[1]]),
                compile_cmd=cmd,
            ))
    return frags
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src /usr/tce/bin/python3 -m pytest src/gen/realcorpus/tests/test_corpus.py -q`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/gen/realcorpus/corpus.py src/gen/realcorpus/tests/test_corpus.py
git commit -m "gen(realcorpus): clean-TU fragment index with feature tags"
```

---

## Task 6: `targets.py` — ordered targets + exemplar priming

**Files:**
- Create: `src/gen/realcorpus/targets.py`
- Create: `src/gen/realcorpus/tests/test_targets.py`

- [ ] **Step 1: Write the failing test**

Create `src/gen/realcorpus/tests/test_targets.py`:
```python
from __future__ import annotations

import json
from pathlib import Path

from foundation.diagnostics.catalog import DiagEntry
from gen.realcorpus.targets import Target, build_targets, load_exemplars


def test_load_exemplars_maps_name_to_erroneous_src(tmp_path: Path):
    ds = tmp_path / "train.jsonl"
    ds.write_text(json.dumps({
        "record_id": "x", "erroneous_src": "int f(){return 0}",
        "corrected_src": "int f(){return 0;}",
        "diagnostics": [{"diag_id": 1, "diag_name": "err_expected_semi",
                         "diag_msg": "m", "file": "f", "line": 1, "col": 1,
                         "start_byte": 0, "end_byte": 1, "span_snippet": "x"}],
        "provenance": {"origin": "guided", "source": "s", "detail": {}},
        "split": "train", "language": "c"}) + "\n")
    ex = load_exemplars(ds)
    assert ex["err_expected_semi"] == "int f(){return 0}"


def test_build_targets_excludes_out_of_scope_and_orders_covered_first():
    entries = [
        DiagEntry(name="err_omp_bad", message="omp"),        # out of scope
        DiagEntry(name="err_uncovered", message="x"),        # in scope, no exemplar
        DiagEntry(name="err_covered", message="y"),          # in scope, has exemplar
    ]
    targets = build_targets(entries, out_of_scope={"err_omp_bad"},
                            exemplars={"err_covered": "buggy"})
    names = [t.name for t in targets]
    assert "err_omp_bad" not in names
    assert names.index("err_covered") < names.index("err_uncovered")  # covered first
    assert targets[0].exemplar == "buggy" and targets[0].covered is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src /usr/tce/bin/python3 -m pytest src/gen/realcorpus/tests/test_targets.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create `src/gen/realcorpus/targets.py`**

```python
"""Build the ordered list of target diagnostics that drives injection.

Targets come from the in-scope error catalog. Each is primed with an exemplar
buggy snippet pulled from the existing dataset (how the diagnostic was triggered
elsewhere) to raise inducibility. Targets are ordered covered-first: a
diagnostic we already have an example for is known-inducible somewhere, so it is
the best bet on real code.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from foundation.diagnostics.catalog import DiagEntry
from gen.realcorpus.features import target_features


@dataclass(frozen=True)
class Target:
    name: str
    message: str
    features: frozenset[str]
    exemplar: Optional[str]       # a buggy snippet that triggered this diagnostic
    covered: bool                 # do we already have an example (exemplar present)?


def load_exemplars(dataset_path: Path) -> dict[str, str]:
    """Map diagnostic name -> one erroneous_src from the existing dataset."""
    ex: dict[str, str] = {}
    for line in Path(dataset_path).read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        diags = d.get("diagnostics") or []
        if not diags:
            continue
        name = diags[0].get("diag_name")
        if name and name not in ex:
            ex[name] = d["erroneous_src"]
    return ex


def build_targets(
    entries: list[DiagEntry],
    out_of_scope: set[str],
    exemplars: dict[str, str],
) -> list[Target]:
    """In-scope targets, covered-first then the rest (stable within each group)."""
    targets: list[Target] = []
    for e in entries:
        if e.name in out_of_scope:
            continue
        exemplar = exemplars.get(e.name)
        targets.append(Target(
            name=e.name, message=e.message or "",
            features=target_features(e.name, e.message or ""),
            exemplar=exemplar, covered=exemplar is not None,
        ))
    targets.sort(key=lambda t: 0 if t.covered else 1)  # stable: covered first
    return targets
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src /usr/tce/bin/python3 -m pytest src/gen/realcorpus/tests/test_targets.py -q`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/gen/realcorpus/targets.py src/gen/realcorpus/tests/test_targets.py
git commit -m "gen(realcorpus): ordered targets with exemplar priming"
```

---

## Task 7: `select.py` — rank fragments for a target

**Files:**
- Create: `src/gen/realcorpus/select.py`
- Create: `src/gen/realcorpus/tests/test_select.py`

- [ ] **Step 1: Write the failing test**

Create `src/gen/realcorpus/tests/test_select.py`:
```python
from __future__ import annotations

from gen.realcorpus.corpus import Fragment
from gen.realcorpus.select import rank_fragments
from gen.realcorpus.targets import Target


def _frag(feats):
    return Fragment(rel_path="f", tu_src="x", span=(0, 1),
                    features=frozenset(feats), compile_cmd=["__CLANG__", "__SRC__"])


def test_rank_prefers_feature_overlap():
    target = Target(name="err_ovl", message="no matching function",
                    features=frozenset({"call"}), exemplar=None, covered=False)
    frags = [_frag(set()), _frag({"call"}), _frag({"template"})]
    ranked = rank_fragments(target, frags, k=2)
    assert ranked[0].features == frozenset({"call"})  # best overlap first
    assert len(ranked) == 2


def test_rank_no_target_features_returns_first_k():
    target = Target(name="err_semi", message="expected ';'",
                    features=frozenset(), exemplar=None, covered=False)
    frags = [_frag({"a"}), _frag({"b"}), _frag({"c"})]
    assert len(rank_fragments(target, frags, k=2)) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src /usr/tce/bin/python3 -m pytest src/gen/realcorpus/tests/test_select.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create `src/gen/realcorpus/select.py`**

```python
"""Rank real fragments for a target diagnostic by feature overlap, so injection
is attempted on plausibly-inducible fragments first. When the target has no
structural feature (e.g. a purely syntactic diagnostic), order is preserved and
the first k are returned."""
from __future__ import annotations

from gen.realcorpus.corpus import Fragment
from gen.realcorpus.targets import Target


def rank_fragments(target: Target, fragments: list[Fragment], *,
                   k: int) -> list[Fragment]:
    if not target.features:
        return fragments[:k]
    scored = sorted(
        enumerate(fragments),
        key=lambda it: (-len(target.features & it[1].features), it[0]),
    )
    return [f for _, f in scored[:k]]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src /usr/tce/bin/python3 -m pytest src/gen/realcorpus/tests/test_select.py -q`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/gen/realcorpus/select.py src/gen/realcorpus/tests/test_select.py
git commit -m "gen(realcorpus): feature-overlap fragment ranking"
```

---

## Task 8: `prompt.py` — injection prompt + edit parsing

**Files:**
- Create: `src/gen/realcorpus/prompt.py`
- Create: `src/gen/realcorpus/tests/test_prompt.py`

- [ ] **Step 1: Write the failing test**

Create `src/gen/realcorpus/tests/test_prompt.py`:
```python
from __future__ import annotations

from gen.realcorpus.prompt import Edit, build_inject_prompt, parse_edit
from gen.realcorpus.targets import Target


def _target():
    return Target(name="err_no_member", message="no member named 'x'",
                  features=frozenset({"member"}), exemplar="s.x;", covered=True)


def test_build_prompt_includes_target_and_region_and_exemplar():
    msgs = build_inject_prompt(_target(), "int f(S s){ return s.y; }", "struct S{int y;};")
    blob = "\n".join(m["content"] for m in msgs)
    assert "err_no_member" in blob
    assert "s.y" in blob            # region text
    assert "s.x;" in blob           # exemplar
    assert any(m["role"] == "system" for m in msgs)


def test_parse_edit_reads_old_new_block():
    reply = "reasoning...\n<<<OLD\nreturn s.y;\n===\nreturn s.zzz;\n>>>"
    e = parse_edit(reply)
    assert e == Edit(old="return s.y;", new="return s.zzz;")


def test_parse_edit_handles_not_applicable_and_junk():
    assert parse_edit("NOT_APPLICABLE") is None
    assert parse_edit("no markers here") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src /usr/tce/bin/python3 -m pytest src/gen/realcorpus/tests/test_prompt.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create `src/gen/realcorpus/prompt.py`**

```python
"""Build the injection chat messages and parse the model's reply.

The model is asked to introduce EXACTLY ONE minimal edit into the given region
so clang emits the target diagnostic, returning an anchored old/new block:

    <<<OLD
    <exact snippet currently in the region>
    ===
    <replacement>
    >>>

or the literal `NOT_APPLICABLE` if the target cannot be naturally induced here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from gen.realcorpus.targets import Target

_SYSTEM = (
    "You corrupt correct C/C++ code to create a SPECIFIC compiler error, for a "
    "compiler-diagnostics dataset. You are given a target Clang diagnostic, an "
    "example of how it is triggered, and a region of real code. Introduce the "
    "SMALLEST possible edit to the region so that Clang emits the target "
    "diagnostic. Keep it realistic and local. Reply with ONE block:\n"
    "<<<OLD\n<exact text to replace, copied verbatim from the region>\n===\n"
    "<replacement text>\n>>>\n"
    "If the target diagnostic cannot be naturally induced in this region, reply "
    "with exactly NOT_APPLICABLE and nothing else."
)

_BLOCK = re.compile(r"<<<OLD\s*\n(.*?)\n===\s*\n(.*?)\n?>>>", re.DOTALL)


@dataclass(frozen=True)
class Edit:
    old: str
    new: str


def build_inject_prompt(target: Target, region_text: str,
                        file_head: str) -> list[dict]:
    exemplar = target.exemplar or "(no example available)"
    user = (
        f"Target diagnostic: {target.name}\n"
        f"Diagnostic message: {target.message}\n\n"
        f"Example that triggers it elsewhere:\n{exemplar}\n\n"
        f"File context (top of file):\n{file_head}\n\n"
        f"Region to edit:\n{region_text}\n"
    )
    return [{"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user}]


def parse_edit(reply: str) -> Optional[Edit]:
    if "NOT_APPLICABLE" in reply and not _BLOCK.search(reply):
        return None
    m = _BLOCK.search(reply)
    if not m:
        return None
    return Edit(old=m.group(1), new=m.group(2))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src /usr/tce/bin/python3 -m pytest src/gen/realcorpus/tests/test_prompt.py -q`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/gen/realcorpus/prompt.py src/gen/realcorpus/tests/test_prompt.py
git commit -m "gen(realcorpus): injection prompt + anchored-edit parsing"
```

---

## Task 9: `inject.py` — apply edit + one model call

**Files:**
- Create: `src/gen/realcorpus/inject.py`
- Create: `src/gen/realcorpus/tests/test_inject.py`

- [ ] **Step 1: Write the failing test**

Create `src/gen/realcorpus/tests/test_inject.py`:
```python
from __future__ import annotations

from gen.realcorpus.corpus import Fragment
from gen.realcorpus.inject import apply_edit, inject_target
from gen.realcorpus.prompt import Edit
from gen.realcorpus.targets import Target


def test_apply_edit_replaces_unique_anchor():
    tu = "int f(){ return 1; }\n"
    assert apply_edit(tu, Edit(old="return 1;", new="return 1")) == "int f(){ return 1 }\n"


def test_apply_edit_rejects_absent_or_nonunique():
    assert apply_edit("a a a", Edit(old="a", new="b")) is None   # non-unique
    assert apply_edit("xyz", Edit(old="q", new="b")) is None     # absent


def test_inject_target_end_to_end_with_mock_chat():
    frag = Fragment(rel_path="f.cpp", tu_src="int f(){ return 1; }\n",
                    span=(0, 20), features=frozenset(), compile_cmd=["__CLANG__", "__SRC__"])
    target = Target(name="err_expected_semi", message="expected ';'",
                    features=frozenset(), exemplar=None, covered=False)

    def chat(messages, temperature):
        return "<<<OLD\nreturn 1;\n===\nreturn 1\n>>>"

    out = inject_target(target, frag, chat, retries=1)
    assert out == "int f(){ return 1 }\n"


def test_inject_target_gives_up_on_not_applicable():
    frag = Fragment(rel_path="f.cpp", tu_src="int f(){ return 1; }\n",
                    span=(0, 20), features=frozenset(), compile_cmd=["__CLANG__", "__SRC__"])
    target = Target(name="err_x", message="x", features=frozenset(),
                    exemplar=None, covered=False)
    out = inject_target(target, frag, lambda m, t: "NOT_APPLICABLE", retries=2)
    assert out is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src /usr/tce/bin/python3 -m pytest src/gen/realcorpus/tests/test_inject.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create `src/gen/realcorpus/inject.py`**

```python
"""Apply an anchored edit to a TU and drive one target-injection attempt.

`chat` is any callable `(messages, temperature) -> reply_text` (the same shape
used by gen/run_scope). Returns the erroneous TU source, or None if the model
declines / the edit can't be uniquely applied within `retries`.
"""
from __future__ import annotations

from typing import Callable, Optional

from gen.realcorpus.corpus import Fragment
from gen.realcorpus.prompt import Edit, build_inject_prompt, parse_edit
from gen.realcorpus.targets import Target

ChatFn = Callable[[list[dict], float], str]

_FILE_HEAD_CHARS = 1200


def apply_edit(tu_src: str, edit: Edit) -> Optional[str]:
    """Replace a UNIQUE occurrence of edit.old with edit.new. None if the anchor
    is absent or appears more than once (ambiguous)."""
    if not edit.old or tu_src.count(edit.old) != 1:
        return None
    return tu_src.replace(edit.old, edit.new, 1)


def inject_target(target: Target, fragment: Fragment, chat: ChatFn, *,
                  retries: int = 2, temperature: float = 0.8) -> Optional[str]:
    file_head = fragment.tu_src[:_FILE_HEAD_CHARS]
    messages = build_inject_prompt(target, fragment.region_text, file_head)
    for _ in range(max(1, retries)):
        try:
            reply = chat(messages, temperature)
        except Exception:
            continue
        edit = parse_edit(reply)
        if edit is None:
            continue
        mutant = apply_edit(fragment.tu_src, edit)
        if mutant is not None and mutant != fragment.tu_src:
            return mutant
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src /usr/tce/bin/python3 -m pytest src/gen/realcorpus/tests/test_inject.py -q`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/gen/realcorpus/inject.py src/gen/realcorpus/tests/test_inject.py
git commit -m "gen(realcorpus): apply anchored edit + one injection attempt"
```

---

## Task 10: `collect.py` — verify + emit Record

**Files:**
- Create: `src/gen/realcorpus/collect.py`
- Create: `src/gen/realcorpus/tests/test_collect.py`

- [ ] **Step 1: Write the failing test**

Create `src/gen/realcorpus/tests/test_collect.py`:
```python
from __future__ import annotations

from foundation.record import Origin, Split
from foundation.types import DiagInfo, VerifierResult
from foundation.verifier.mock import MockVerifier, ok_result
from gen.realcorpus.collect import collect_real_record, count_errors
from gen.realcorpus.corpus import Fragment
from gen.realcorpus.targets import Target


def _frag():
    return Fragment(rel_path="clang/lib/A.cpp", tu_src="int f(){ return 0; }\n",
                    span=(0, 19), features=frozenset(), compile_cmd=["__CLANG__", "__SRC__"])


def _target(name="err_expected_semi"):
    return Target(name=name, message="expected ';'", features=frozenset(),
                  exemplar=None, covered=True)


def test_count_errors_counts_error_lines():
    assert count_errors("a.c:1:1: error: x\na.c:2:1: error: y\n") == 2


def test_collect_emits_record_with_cascade_and_target_match():
    stderr = "a.cpp:1:9: error: expected ';'\nDiagID: 1\na.cpp:1:9: error: cascade\n"
    diag = DiagInfo(diag_id=1, diag_name="err_expected_semi", diag_msg="expected ';'",
                    file="clang/lib/A.cpp", line=1, col=9, start_byte=0, end_byte=1,
                    span_snippet="x")

    def policy(src, cmd, logical_path):
        return VerifierResult(ok=False, diag=diag, raw_stderr=stderr)

    rec = collect_real_record(_frag(), "int f(){ return 0 }\n", _target(),
                              MockVerifier(policy), split=Split.EVAL)
    assert rec is not None
    assert rec.provenance.origin == Origin.GUIDED
    assert rec.provenance.detail["cascade_size"] == 2
    assert rec.provenance.detail["primary_matches_target"] is True
    assert rec.provenance.detail["target_diag"] == "err_expected_semi"
    assert rec.corrected_src == "int f(){ return 0; }\n"


def test_collect_returns_none_when_mutant_still_compiles():
    rec = collect_real_record(_frag(), "int f(){ return 0; }\n", _target(),
                              MockVerifier(lambda s, c, l: ok_result()))
    assert rec is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src /usr/tce/bin/python3 -m pytest src/gen/realcorpus/tests/test_collect.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create `src/gen/realcorpus/collect.py`**

```python
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
) -> Optional[Record]:
    res = verifier.verify(erroneous_src, fragment.compile_cmd,
                          logical_path=fragment.rel_path)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src /usr/tce/bin/python3 -m pytest src/gen/realcorpus/tests/test_collect.py -q`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/gen/realcorpus/collect.py src/gen/realcorpus/tests/test_collect.py
git commit -m "gen(realcorpus): verify injected mutant + emit tagged Record"
```

---

## Task 11: `run_realcorpus.py` — CLI driver

**Files:**
- Create: `src/gen/realcorpus/run_realcorpus.py`
- Create: `src/gen/realcorpus/tests/test_driver.py`

The driver's testable core is `drive_targets` (pure orchestration over injected
functions); the `main()` wires real backends around it.

- [ ] **Step 1: Write the failing test**

Create `src/gen/realcorpus/tests/test_driver.py`:
```python
from __future__ import annotations

from foundation.types import DiagInfo, VerifierResult
from foundation.verifier.mock import MockVerifier
from gen.realcorpus.corpus import Fragment
from gen.realcorpus.run_realcorpus import drive_targets, to_run_sweep_row
from gen.realcorpus.targets import Target


def _frag(feats=frozenset()):
    return Fragment(rel_path="clang/lib/A.cpp", tu_src="int f(){ return 0; }\n",
                    span=(0, 19), features=feats, compile_cmd=["__CLANG__", "__SRC__"])


def test_drive_targets_emits_one_record_per_success_up_to_cap():
    targets = [Target(name=f"err_{i}", message="m", features=frozenset(),
                      exemplar=None, covered=True) for i in range(3)]
    frags = [_frag()]
    diag = DiagInfo(diag_id=1, diag_name="err_0", diag_msg="m", file="clang/lib/A.cpp",
                    line=1, col=1, start_byte=0, end_byte=1, span_snippet="x")

    def verify(src, cmd, logical_path):
        return VerifierResult(ok=False, diag=diag, raw_stderr="a:1:1: error: m\n")

    def inject(target, fragment, chat, **kw):        # always succeeds
        return "int f(){ return 0 }\n"

    recs = drive_targets(targets, frags, MockVerifier(verify), chat=None,
                         inject_fn=inject, candidates_per_target=2, max_instances=2)
    assert len(recs) == 2                            # capped
    assert to_run_sweep_row(recs[0], frags[0])["compile_cmd"] == ["__CLANG__", "__SRC__"]
    assert "cascade_size" in to_run_sweep_row(recs[0], frags[0])


def test_drive_targets_skips_targets_that_never_inject():
    targets = [Target(name="err_x", message="m", features=frozenset(),
                      exemplar=None, covered=True)]
    recs = drive_targets(targets, [_frag()], MockVerifier(lambda s, c, l: None),
                         chat=None, inject_fn=lambda *a, **k: None,
                         candidates_per_target=2, max_instances=5)
    assert recs == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src /usr/tce/bin/python3 -m pytest src/gen/realcorpus/tests/test_driver.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create `src/gen/realcorpus/run_realcorpus.py`**

```python
#!/usr/bin/env python3
"""Target-first real-code error injection driver.

For each in-scope target diagnostic (covered-first), pick feature-relevant real
fragments, ask the model for a minimal edit that triggers the target, verify
with the real compile command, and emit run_sweep-format rows. Bounded by
--max-instances (the first eval slice = the highest-yield prefix of the
catalog).

    PYTHONPATH=src /usr/tce/bin/python3 src/gen/realcorpus/run_realcorpus.py \\
      --compile-db /p/lustre2/shan4/fuzzlang-llvm-build/compile_commands.json \\
      --clang-bin $FUZZLANG_CLANG_BIN --diagtool-bin $FUZZLANG_DIAGTOOL_BIN \\
      --dataset data/gen/splits/train.jsonl \\
      --out-of-scope data/gen/out_of_scope.txt \\
      --model gpt-5.4-mini --base-url https://api.openai.com/v1 \\
      --n-files 300 --candidates-per-target 4 --max-instances 300 \\
      --out data/gen/splits/eval_realcorpus.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Callable, Optional

from foundation.compile_db import load_compile_db
from foundation.diagnostics.catalog import load_catalog
from foundation.record import Record, Split
from foundation.verifier import FuzzlangClangVerifier
from gen.realcorpus.collect import collect_real_record
from gen.realcorpus.corpus import Fragment, build_fragment_index
from gen.realcorpus.inject import inject_target
from gen.realcorpus.select import rank_fragments
from gen.realcorpus.targets import Target, build_targets, load_exemplars


def drive_targets(
    targets: list[Target],
    fragments: list[Fragment],
    verifier,
    *,
    chat,
    inject_fn: Callable = inject_target,
    candidates_per_target: int,
    max_instances: int,
    split: Split = Split.EVAL,
) -> list[Record]:
    """Core orchestration: one emitted Record per target that injects+verifies,
    up to max_instances. `inject_fn` is injectable for testing."""
    out: list[Record] = []
    for target in targets:
        if len(out) >= max_instances:
            break
        for frag in rank_fragments(target, fragments, k=candidates_per_target):
            erroneous = inject_fn(target, frag, chat)
            if erroneous is None:
                continue
            lang = "c" if frag.rel_path.endswith(".c") else "c++"
            rec = collect_real_record(frag, erroneous, target, verifier,
                                      split=split, language=lang)
            if rec is not None:
                out.append(rec)
                break  # one instance per target; move on
    return out


def to_run_sweep_row(rec: Record, fragment: Fragment) -> dict:
    d = rec.primary_diagnostic
    det = rec.provenance.detail
    return {
        "instance_id": rec.record_id,
        "buggy_src": rec.erroneous_src,
        "corrected_src": rec.corrected_src,
        "compile_cmd": fragment.compile_cmd,
        "diag_id": d.diag_id if d else None,
        "diag_name": d.diag_name if d else None,
        "language": rec.language,
        "cascade_size": det.get("cascade_size"),
        "target_diag": det.get("target_diag"),
        "primary_matches_target": det.get("primary_matches_target"),
    }


def _chat_fn(model: str, base_url: str):
    from repair.agent.chat_backend import OpenAIChatBackend
    backend = OpenAIChatBackend(model, base_url=base_url,
                               api_key=os.environ.get("OPENAI_API_KEY", "EMPTY"))

    def chat(messages, temperature: float) -> str:
        r = backend.chat(messages=messages, temperature=temperature,
                         max_tokens=512, n=1)
        return r[0].text if r else ""
    return chat


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--compile-db", type=Path, required=True)
    ap.add_argument("--clang-bin", required=True)
    ap.add_argument("--diagtool-bin", required=True)
    ap.add_argument("--dataset", type=Path, required=True, help="exemplar source JSONL")
    ap.add_argument("--out-of-scope", type=Path, required=True)
    ap.add_argument("--model", default="gpt-5.4-mini")
    ap.add_argument("--base-url", default="https://api.openai.com/v1")
    ap.add_argument("--n-files", type=int, default=300)
    ap.add_argument("--candidates-per-target", type=int, default=4)
    ap.add_argument("--max-instances", type=int, default=300)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    verifier = FuzzlangClangVerifier(clang_bin=args.clang_bin,
                                     diagtool_bin=args.diagtool_bin, timeout_s=30.0)
    db = load_compile_db(args.compile_db)
    print(f"[realcorpus] compile db: {len(db)} TUs", flush=True)
    frags = build_fragment_index(db, verifier, n_files=args.n_files, seed=args.seed)
    print(f"[realcorpus] fragment pool: {len(frags)} fragments", flush=True)

    out_of_scope = {l.strip() for l in args.out_of_scope.read_text().splitlines()
                    if l.strip()}
    exemplars = load_exemplars(args.dataset)
    targets = build_targets(load_catalog().errors(), out_of_scope, exemplars)
    print(f"[realcorpus] targets: {len(targets)} in-scope "
          f"({sum(t.covered for t in targets)} covered-first)", flush=True)

    chat = _chat_fn(args.model, args.base_url)

    # main() inlines the drive loop (vs. calling drive_targets) so it can stream
    # progress and rows; drive_targets stays the unit-tested pure core.
    records: list[Record] = []
    rows: list[dict] = []
    remaining = args.max_instances
    for target in targets:
        if remaining <= 0:
            break
        for frag in rank_fragments(target, frags, k=args.candidates_per_target):
            erroneous = inject_target(target, frag, chat)
            if erroneous is None:
                continue
            lang = "c" if frag.rel_path.endswith(".c") else "c++"
            rec = collect_real_record(frag, erroneous, target, verifier, language=lang)
            if rec is not None:
                records.append(rec)
                rows.append(to_run_sweep_row(rec, frag))
                remaining -= 1
                print(f"[realcorpus] {len(rows)}/{args.max_instances} "
                      f"{target.name} match={rec.provenance.detail['primary_matches_target']} "
                      f"cascade={rec.provenance.detail['cascade_size']}", flush=True)
                break

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    matched = sum(1 for r in rows if r["primary_matches_target"])
    print(f"[realcorpus] DONE wrote {len(rows)} rows -> {args.out} "
          f"({matched} primary==target)", flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src /usr/tce/bin/python3 -m pytest src/gen/realcorpus/tests/test_driver.py -q`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the whole module test suite + full suite**

Run: `PYTHONPATH=src /usr/tce/bin/python3 -m pytest src/gen/realcorpus src/foundation/tests/test_compile_db.py -q`
Expected: PASS (all).
Run: `PYTHONPATH=src /usr/tce/bin/python3 -m pytest -q`
Expected: PASS (no regressions across the repo).

- [ ] **Step 6: Commit**

```bash
git add src/gen/realcorpus/run_realcorpus.py src/gen/realcorpus/tests/test_driver.py
git commit -m "gen(realcorpus): target-first injection driver + run_sweep row emit"
```

---

## Task 12: Integration smoke against real clang + OpenAI (ops)

**Files:** none (produces a data artifact on scratch, not committed).

- [ ] **Step 1: Run a tiny real slice**

```bash
cd /p/lustre2/shan4/new-fuzzlang
export FUZZLANG_CLANG_BIN=/p/lustre2/shan4/fuzzlang-clang/bin/clang
export FUZZLANG_DIAGTOOL_BIN=/p/lustre2/shan4/fuzzlang-clang/bin/diagtool
source /p/lustre1/shan4/.fuzzlang_openai_key   # sets OPENAI_API_KEY in env, not argv
export OPENAI_API_KEY PYTHONPATH=src
/usr/tce/bin/python3 src/gen/realcorpus/run_realcorpus.py \
  --compile-db /p/lustre2/shan4/fuzzlang-llvm-build/compile_commands.json \
  --clang-bin $FUZZLANG_CLANG_BIN --diagtool-bin $FUZZLANG_DIAGTOOL_BIN \
  --dataset data/gen/splits/train.jsonl \
  --out-of-scope data/gen/out_of_scope.txt \
  --model gpt-5.4-mini --base-url https://api.openai.com/v1 \
  --n-files 40 --candidates-per-target 3 --max-instances 15 \
  --out /p/lustre1/shan4/fuzzlang-repair/realcorpus_smoke.jsonl
```
Expected: fragment pool builds (non-zero), and several rows are written with a
mix of `primary_matches_target` true/false and varying `cascade_size`. Model
calls use `gpt-5.4-mini` only.

- [ ] **Step 2: Sanity-check a row reproduces under the verifier**

```bash
PYTHONPATH=src /usr/tce/bin/python3 - <<'PY'
import json
from foundation.verifier import FuzzlangClangVerifier
import os
v=FuzzlangClangVerifier(os.environ["FUZZLANG_CLANG_BIN"], os.environ["FUZZLANG_DIAGTOOL_BIN"], timeout_s=30)
row=json.loads(open("/p/lustre1/shan4/fuzzlang-repair/realcorpus_smoke.jsonl").readline())
rb=v.verify(row["buggy_src"], row["compile_cmd"], logical_path=row["instance_id"])
rc=v.verify(row["corrected_src"], row["compile_cmd"], logical_path=row["instance_id"])
print("buggy errors:", not rb.ok, "| corrected clean:", rc.ok,
      "| primary:", rb.diag.diag_name if rb.diag else None,
      "| target:", row["target_diag"], "| cascade:", row["cascade_size"])
assert not rb.ok and rc.ok
PY
```
Expected: `buggy errors: True | corrected clean: True`.

- [ ] **Step 3: Decide scale**

If the smoke yields clean instances, scale up (`--n-files 300 --max-instances 300`)
and write to `data/gen/splits/eval_realcorpus.jsonl`. If the fragment pool is
tiny or yield is near-zero, tune `--n-files` / retries and re-check the
compile-env assumptions from Task 1 before scaling. Report the honest per-run
yield.

---

## Task 13: Repair experiment on the real-code slice (ops)

**Files:** none (reuses `run_sweep.py` + `aggregate_eval.py`).

- [ ] **Step 1: Run b0/b1/diag on the slice**

Reuse the existing driver (login node; OpenAI needs internet):
```bash
cd /p/lustre2/shan4/new-fuzzlang
export FUZZLANG_CLANG_BIN=/p/lustre2/shan4/fuzzlang-clang/bin/clang
export FUZZLANG_DIAGTOOL_BIN=/p/lustre2/shan4/fuzzlang-clang/bin/diagtool
source /p/lustre1/shan4/.fuzzlang_openai_key; export OPENAI_API_KEY PYTHONPATH=src
SLICE=data/gen/splits/eval_realcorpus.jsonl
OUT=/p/lustre1/shan4/fuzzlang-repair/realfull; mkdir -p "$OUT"
for m in b0_zero_shot b1_stderr_loop diag; do for s in 0 1 2; do
  /usr/tce/bin/python3 src/repair/run_sweep.py --method $m --seed $s --split $SLICE \
    --model-name gpt-5.4-mini --base-url https://api.openai.com/v1 \
    --clang-bin $FUZZLANG_CLANG_BIN --diagtool-bin $FUZZLANG_DIAGTOOL_BIN \
    --T 5 --K 4 --token-envelope 5120 --workers 24 --out "$OUT/${m}_s${s}.json"
done; done
```

- [ ] **Step 2: Aggregate, sliced by cascade depth**

`aggregate_eval.py` already reports micro/macro + CIs + per-family + mean
turns/tokens. Run it, then additionally compute fix-rate bucketed by
`cascade_size` from the instance JSONL joined on `instance_id` (single-error vs
cascade), and the diag − b1 delta per bucket. Append the table to
`docs/FuzzLang-progress.md` under a new "Repair on real-code slice" section.
Commit (no Claude signature, fetch before push).

- [ ] **Step 3: Commit the write-up**

```bash
git add docs/FuzzLang-progress.md
git commit -m "docs: repair on real-code injected slice (fix-rate by cascade depth)"
```

---

## Self-review notes (checked against the spec)

- **Spec coverage:** target-first driver (Task 6/11), full in-scope catalog minus out-of-scope (Task 6), inducibility order = covered-first (Task 6), exemplar priming (Task 6/8), feature-ranked SELECT (Task 4/7), region-scoped localized edit / Approach A (Task 8/9), accept single+cascade & tag cascade_size + primary_matches_target (Task 10), real per-file compile cmd via extracted compile_db (Task 2), run_sweep-format output (Task 11), experiment sliced by cascade depth (Task 13), 22.1.8 consistency (Task 1 — already satisfied). All covered.
- **Provenance:** reuses `Origin.GUIDED` per spec default; a dedicated `Origin.REAL_INJECT` remains an optional follow-up (would touch `foundation/record.py` + `to_dict`/`from_dict` only).
- **Type consistency:** `Fragment`, `Target`, `Edit`, `ChatFn` signatures are consistent across Tasks 5–11; `drive_targets`/`inject_target` signatures match their tests.
