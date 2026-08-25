#!/bin/bash
# E10: repair rate on errors FuzzLang did not create.
#
# Every other evaluation uses real source with errors *we* injected. This uses
# the NatErr set: errors developers actually made, recovered from LLVM commit
# history and revalidated by the same pinned Clang. It is the only measurement
# we have of repair on errors from outside our own generator.
#
# n=3. That is not a benchmark, and the report must not present it as one. It
# is worth running because the alternative is having no number at all for the
# question a reviewer will certainly ask.
set -uo pipefail
# The verifier compiles deliberately broken source, so Clang crashes are
# routine. Each crash dropped a core file into the working directory --
# 124 of them accumulated, all truncated to 16KB and useless for debugging.
ulimit -c 0

REPO=${REPO:-/p/lustre2/shan4/new-fuzzlang}
DATA=${DATA:-$REPO/data/natErr/formal-20260812/records-union.jsonl}
BASE=${BASE:-$REPO/.artifacts/models/gemma-3-4b-it}
ADAPTER=${ADAPTER:-$REPO/.artifacts/sft-runs/e5-scaling/fuzzlang4000-seed42/adapter}
OUT=${OUT:-$REPO/.artifacts/sft-eval/e10-naterr}
PY=${PY:-/p/lustre1/shan4/gemma/venv/bin/python}

cd "$REPO"
mkdir -p "$OUT"

run() {  # label  adapter-or-empty
    local out="$OUT/$1--naterr.json"
    if [ -s "$out" ]; then echo "SKIP $1"; return; fi
    local args=(); [ -n "$2" ] && args=(--adapter "$2")
    echo "=== $1 start $(date +%H:%M:%S)"
    PYTHONPATH=src "$PY" src/repair/run_adapter_eval.py \
        --base-model "$BASE" "${args[@]}" \
        --data-path "$DATA" \
        --clang-bin /p/lustre2/shan4/fuzzlang-clang/bin/clang++ \
        --clang-c-bin /p/lustre2/shan4/fuzzlang-clang/bin/clang \
        --diagtool-bin /p/lustre2/shan4/fuzzlang-clang/bin/diagtool \
        --out "$out" --max-instances 8 --max-new-tokens 512 --seed 42 \
        --target-format window-rewrite --local-files-only 2>&1 | tail -6 \
        || echo "FAIL $1"
}

run base ""
run fuzzlang4000 "$ADAPTER"
echo "=== E10 DONE $(date +%H:%M:%S)"
