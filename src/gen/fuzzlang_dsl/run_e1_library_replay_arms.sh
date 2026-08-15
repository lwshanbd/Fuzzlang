#!/bin/bash
# E1: replay the released Injector library over every split and both operation
# families.  CPU only, one node, zero model calls.
#
#   lexical  (replace/insert/delete) -- the genuine cross-source transfer claim
#   append   (self-contained fragment) -- matches any file, reported separately
#
#   train            -- the corpus that may become training data
#   eval_unseen_tu   -- held-out files inside training projects
#   heldout_project  -- projects that contribute no training data at all
set -uo pipefail

REPO=${REPO:-/p/lustre2/shan4/new-fuzzlang}
RUN=${RUN:-$REPO/data/gen/experiments/e1-library-replay-v0001}
SPLIT_DIR=${SPLIT_DIR:-$REPO/data/gen/source-pools/e1-splits-v0001}
LIB=${LIB:-$RUN/library.jsonl}
WORKERS=${WORKERS:-32}
VERIFY_TIMEOUT=${VERIFY_TIMEOUT:-90}
MAX_VERIFICATIONS=${MAX_VERIFICATIONS:-24}
MAX_PER_SOURCE=${MAX_PER_SOURCE:-3}
MAX_PER_DIAG=${MAX_PER_DIAG:-5}

cd "$REPO"
SRC=()
for f in "$SPLIT_DIR"/*.sources.split.jsonl; do SRC+=(--sources "$f"); done
if [ ${#SRC[@]} -eq 0 ]; then echo "no split-labelled pools in $SPLIT_DIR" >&2; exit 2; fi

for ops in lexical append; do
    for split in train eval_unseen_tu heldout_project; do
        out="$RUN/$ops-$split"
        if [ -s "$out/manifest.json" ]; then echo "SKIP $ops/$split"; continue; fi
        echo "=== $ops / $split"
        PYTHONPATH=src python3 src/gen/fuzzlang_dsl/run_e1_library_replay.py \
            --injectors "$LIB" "${SRC[@]}" \
            --split "$split" --operations "$ops" --out-dir "$out" \
            --clang-bin /p/lustre2/shan4/fuzzlang-clang/bin/clang++ \
            --clang-c-bin /p/lustre2/shan4/fuzzlang-clang/bin/clang \
            --diagtool-bin /p/lustre2/shan4/fuzzlang-clang/bin/diagtool \
            --max-workers "$WORKERS" --verify-timeout "$VERIFY_TIMEOUT" \
            --max-verifications-per-source "$MAX_VERIFICATIONS" \
            --max-records-per-source "$MAX_PER_SOURCE" \
            --max-records-per-diagnostic "$MAX_PER_DIAG" 2>&1 | tail -30 \
            || echo "FAIL $ops/$split"
    done
done
echo "=== ALL DONE ==="
