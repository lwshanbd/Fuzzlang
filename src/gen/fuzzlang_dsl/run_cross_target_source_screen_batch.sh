#!/usr/bin/env bash
# Re-clean-gate one known production C++ TU for several target triples inside
# one already allocated CPU node.  It intentionally starts no nested Flux job.
set -euo pipefail

ROOT=/p/lustre2/shan4/new-fuzzlang
OUT="$ROOT/data/gen/source-pools/llvm-22.1.8-cross-target-noinclude-v0001"
INPUT="$OUT/sources.jsonl"
CLANG_CXX=/p/lustre2/shan4/fuzzlang-clang/bin/clang++
CLANG_C=/p/lustre2/shan4/fuzzlang-clang/bin/clang
DIAGTOOL=/p/lustre2/shan4/fuzzlang-clang/bin/diagtool

cd "$ROOT"
export PYTHONPATH=src${PYTHONPATH:+:$PYTHONPATH}

# These are exact target triples observed in the Clang regression-test RUN
# lines.  Do not silently substitute a different platform or ABI.
for spec in \
  x86_64_linux:x86_64-linux-gnu \
  x86_64_unknown_linux:x86_64-unknown-linux-gnu \
  i386_linux:i386-linux \
  i386_apple_darwin9:i386-apple-darwin9; do
  label=${spec%%:*}
  target=${spec#*:}
  python3 src/gen/realcorpus/run_revalidate_cpp_standard_pool.py \
    --clean-sources "$INPUT" --language c++ --standard c++23 \
    --append-arg=--target="$target" \
    --clang-bin "$CLANG_CXX" --clang-c-bin "$CLANG_C" --diagtool-bin "$DIAGTOOL" \
    --out "$OUT/$label-sources.jsonl" \
    --rejections-out "$OUT/$label-rejections.jsonl" \
    --manifest-out "$OUT/$label-manifest.json" \
    --workers 8 --timeout 20
done
