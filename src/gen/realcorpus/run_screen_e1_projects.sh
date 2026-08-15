#!/bin/bash
# Build a clean, non-test source pool for every candidate E1 project that has a
# compile database.  CPU only: this compiles each translation unit once with the
# pinned patched Clang to prove it is a valid clean parent.  One node.
set -uo pipefail

REPO=${REPO:-/p/lustre2/shan4/new-fuzzlang}
CORPORA=${CORPORA:-/p/vast1/shan4/fuzzlang-corpora-e1}
OUT=${OUT:-$REPO/data/gen/source-pools}
CLANGXX=/p/lustre2/shan4/fuzzlang-clang/bin/clang++
CLANGC=/p/lustre2/shan4/fuzzlang-clang/bin/clang
DIAGTOOL=/p/lustre2/shan4/fuzzlang-clang/bin/diagtool
WORKERS=${WORKERS:-32}
TIMEOUT=${TIMEOUT:-60}
TAG=${TAG:-e1-v0001}

cd "$REPO"
for db in "$CORPORA"/*/build/compile_commands.json; do
    [ -f "$db" ] || continue
    project=$(basename "$(dirname "$(dirname "$db")")")
    root="$CORPORA/$project"
    dest="$OUT/${project}-${TAG}"
    if [ -s "$dest/sources.jsonl" ]; then
        echo "SKIP $project (pool exists)"
        continue
    fi
    mkdir -p "$dest"
    echo "=== screening $project"
    PYTHONPATH=src python3 src/gen/realcorpus/run_clean_source_pool.py \
        --compile-db "$db" \
        --clang-bin "$CLANGXX" --clang-c-bin "$CLANGC" --diagtool-bin "$DIAGTOOL" \
        --project "$project" --source-root "$root" \
        --out "$dest/sources.jsonl" \
        --rejections-out "$dest/rejections.jsonl" \
        --manifest-out "$dest/manifest.json" \
        --workers "$WORKERS" --timeout "$TIMEOUT" \
        && echo "OK $project clean=$(wc -l < "$dest/sources.jsonl")" \
        || echo "FAIL $project"
done
echo "=== pool summary ==="
for f in "$OUT"/*-${TAG}/sources.jsonl; do
    [ -f "$f" ] && echo "$(wc -l < "$f") $(basename "$(dirname "$f")")"
done | sort -rn
