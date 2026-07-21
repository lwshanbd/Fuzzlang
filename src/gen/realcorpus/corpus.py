"""Build a feature-indexed pool of real code fragments.

Each fragment is a function span from a real LLVM TU that compiles CLEAN under
its own (patched-clang) compile command — the correct-code invariant at the TU
level. Fragments carry their placeholdered compile command so a later injected
mutant can be verified with the exact real flags.
"""
from __future__ import annotations

import random
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from foundation.compile_db import build_clang_argv
from foundation.verifier.base import BaseVerifier
from gen.realcorpus.features import fragment_features
from gen.realcorpus.region import select_typed_regions

_SRC_EXTS = (".c", ".cc", ".cpp", ".cxx", ".c++")

# Path components whose files are NOT proper project source (tests, test tools,
# examples, benchmarks, fuzzers, vendored gtest/gmock).  Match the token even
# inside names such as c-index-test, llvm-c-test, TestPasses.cpp, and
# TestingSupport.cpp, and TaintTesterChecker.cpp: those are compiled by LLVM
# but are still test-oriented code and must not enter the real-project corpus.
_TEST_COMPONENTS = frozenset({
    "test", "tests", "unittest", "unittests", "gtest", "gmock",
    "googletest", "googlemock", "example", "examples", "benchmark",
    "benchmarks", "fuzz", "fuzzer", "fuzzing",
})
_TEST_HYPHEN_TOKEN_RE = re.compile(
    r"(?:^|-)(?:test|tests|gtest|gmock|example|examples|benchmark|benchmarks|"
    r"fuzz|fuzzer|fuzzing)(?:-|$)", re.I)
_TEST_CAMEL_RE = re.compile(r"(?:Testing|Tester|Test)(?:[A-Z]|$)")


def is_test_path(path: str) -> bool:
    """True for conventional and test-named tool/support paths.

    Token-aware matching avoids rejecting an unrelated parent such as a pytest
    temporary directory named ``test_build_fragment_index...`` while still
    catching LLVM components like ``c-index-test`` and ``TestingSupport.cpp``.
    """
    parts = [part for part in path.replace("\\", "/").split("/") if part]
    for i, part in enumerate(parts):
        stem = part.rsplit(".", 1)[0]
        lower = stem.lower()
        if lower in _TEST_COMPONENTS or _TEST_HYPHEN_TOKEN_RE.search(lower):
            return True
        if _TEST_CAMEL_RE.search(stem):
            return True
        if i == len(parts) - 1 and (
                lower.startswith("test_") or lower.endswith("_test")):
            return True
    return False


@dataclass(frozen=True)
class Fragment:
    rel_path: str                 # source path (as recorded in the compile DB)
    tu_src: str                   # full translation-unit text
    span: tuple[int, int]         # (start, end) char offsets of the region in tu_src
    features: frozenset[str]
    compile_cmd: list[str]        # placeholdered: [__CLANG__ ... __SRC__]
    region_type: str = "function"

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
    min_region_lines: int = 0,
    path_filter=None,
    workers: int = 8,
) -> list[Fragment]:
    """Sample up to `n_files` PROPER-SOURCE C/C++ TUs (test/example dirs always
    excluded; plus an optional `path_filter` predicate), keep those that compile
    clean under the patched clang, and emit one Fragment per function span.
    The per-file work (read + clean-compile + region extract) runs in a thread
    pool of `workers`."""
    files = [f for f in db
             if f.lower().endswith(_SRC_EXTS) and not is_test_path(f)]
    if path_filter is not None:
        files = [f for f in files if path_filter(f)]
    rng = random.Random(seed)
    rng.shuffle(files)
    files = files[:n_files]

    def process(abs_path: str) -> list[Fragment]:
        entry = db[abs_path]
        try:
            tu_src = Path(abs_path).read_text(errors="replace")
        except OSError:
            return []
        cmd = sanitize_cmd(build_clang_argv(entry, "__CLANG__", "__SRC__"))
        base = verifier.verify(tu_src, cmd, logical_path=abs_path)
        if not base.ok:
            return []
        frags: list[Fragment] = []
        for region in select_typed_regions(
                tu_src, max_regions=max_regions_per_file,
                min_lines=min_region_lines):
            span = region.span
            frags.append(Fragment(
                rel_path=entry["file"], tu_src=tu_src, span=span,
                features=fragment_features(tu_src[span[0]:span[1]]),
                compile_cmd=cmd, region_type=region.kind))
        return frags

    out: list[Fragment] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        for res in ex.map(process, files):
            out.extend(res)
    return out
