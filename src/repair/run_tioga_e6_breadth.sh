#!/bin/bash
# E6, one arm: is it more data, or more *kinds* of error?
#
# E5 grew record count and diagnostic coverage together, so it cannot separate
# them -- and breadth is FuzzLang's distinctive claim. These two arms hold the
# record count at 3,500 and move only coverage: `broad` spans 427 diagnostics,
# `narrow` concentrates the same 3,500 records on 135. Rendered tokens differ by
# 4%, so the comparison is about which errors are represented, not how much text.
set -uo pipefail
# The verifier compiles deliberately broken source, so Clang crashes are
# routine. Each crash dropped a core file into the working directory --
# 124 of them accumulated, all truncated to 16KB and useless for debugging.
ulimit -c 0

REPO=${REPO:-/p/lustre2/shan4/new-fuzzlang}
MODE=${MODE:?MODE (broad|narrow) is required}
COUNT=${COUNT:-3500}
SEED=${SEED:-42}
ARMS=${ARMS:-$REPO/.artifacts/sft-arms/e6-breadth-seed42}
RUNS=${RUNS:-$REPO/.artifacts/sft-runs/e6-breadth}
EVAL=${EVAL:-$REPO/.artifacts/sft-eval/e6-breadth}
BASE=${BASE:-$REPO/.artifacts/models/gemma-3-4b-it}
REVISION=${REVISION:-093f9f388b31de276ce2de164bdc2081324b9767}
COHORTS=${COHORTS:-$REPO/data/gen/experiments/e3-eval-cohorts-v0001}
EPOCHS=${EPOCHS:-3}
BATCH=${BATCH:-1}
GRAD_ACCUM=${GRAD_ACCUM:-2}
LR=${LR:-2e-4}
MAX_SEQ_LEN=${MAX_SEQ_LEN:-1024}
PY=${PY:-/p/lustre1/shan4/gemma/venv/bin/python}

cd "$REPO"
run="$RUNS/${MODE}${COUNT}-seed${SEED}"
mkdir -p "$run" "$EVAL"

if [ -s "$run/adapter/run-manifest.json" ]; then
    echo "SKIP train $MODE"
else
    echo "=== train $MODE ($COUNT records) start $(date +%H:%M:%S)"
    PYTHONPATH=src "$PY" src/repair/run_sft.py \
        --base-model "$BASE" --model-revision "$REVISION" \
        --data-path "$ARMS/fuzzlang-${MODE}-${COUNT}.train.jsonl" \
        --adapter-out "$run/adapter" \
        --target-format window-rewrite \
        --epochs "$EPOCHS" --batch-size "$BATCH" --grad-accum "$GRAD_ACCUM" \
        --lr "$LR" --seed "$SEED" --max-seq-len "$MAX_SEQ_LEN" \
        --bf16 --local-files-only --no-gradient-checkpointing 2>&1 | tail -8 \
        || { echo "FAIL train $MODE"; exit 1; }
    echo "=== train $MODE done $(date +%H:%M:%S)"
fi

for cohort in eval_unseen_tu heldout_project; do
    out="$EVAL/${MODE}${COUNT}-seed${SEED}--${cohort}.json"
    if [ -s "$out" ]; then echo "SKIP eval $MODE / $cohort"; continue; fi
    echo "=== eval $MODE / $cohort start $(date +%H:%M:%S)"
    PYTHONPATH=src "$PY" src/repair/run_adapter_eval.py \
        --base-model "$BASE" --adapter "$run/adapter" \
        --data-path "$COHORTS/${cohort}.jsonl" \
        --clang-bin /p/lustre2/shan4/fuzzlang-clang/bin/clang++ \
        --clang-c-bin /p/lustre2/shan4/fuzzlang-clang/bin/clang \
        --diagtool-bin /p/lustre2/shan4/fuzzlang-clang/bin/diagtool \
        --out "$out" --max-instances 150 --max-new-tokens 512 --seed 42 \
        --target-format window-rewrite \
        --local-files-only 2>&1 | tail -5 || echo "FAIL eval $MODE / $cohort"
done
echo "=== E6 $MODE DONE $(date +%H:%M:%S)"
