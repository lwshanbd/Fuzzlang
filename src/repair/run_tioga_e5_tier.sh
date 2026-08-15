#!/bin/bash
# E5, one tier: train the FuzzLang arm at SIZE records, then evaluate it on both
# held-out cohorts.
#
# One tier per job, deliberately.  A single job covering all three tiers needs a
# ~12h reservation, which the scheduler pushes out for hours even while nodes
# sit free; three short jobs backfill immediately and run concurrently.  Tiers
# are independent -- nested subsets are decided at arm-build time, not here.
set -uo pipefail

REPO=${REPO:-/p/lustre2/shan4/new-fuzzlang}
SIZE=${SIZE:?SIZE (557|1500|4000) is required}
SEED=${SEED:-42}
ARMS=${ARMS:-$REPO/.artifacts/sft-arms/e5-scaling-seed42}
RUNS=${RUNS:-$REPO/.artifacts/sft-runs/e5-scaling}
EVAL=${EVAL:-$REPO/.artifacts/sft-eval/e5-scaling}
BASE=${BASE:-$REPO/.artifacts/models/gemma-3-4b-it}
REVISION=${REVISION:-093f9f388b31de276ce2de164bdc2081324b9767}
COHORTS=${COHORTS:-$REPO/data/gen/experiments/e3-eval-cohorts-v0001}
EPOCHS=${EPOCHS:-3}
BATCH=${BATCH:-1}
GRAD_ACCUM=${GRAD_ACCUM:-2}
LR=${LR:-2e-4}
MAX_SEQ_LEN=${MAX_SEQ_LEN:-1024}
MAX_INSTANCES=${MAX_INSTANCES:-150}
MAX_NEW_TOKENS=${MAX_NEW_TOKENS:-512}
PY=${PY:-/p/lustre1/shan4/gemma/venv/bin/python}

cd "$REPO"
run="$RUNS/fuzzlang${SIZE}-seed${SEED}"
mkdir -p "$run" "$EVAL"

if [ -s "$run/adapter/run-manifest.json" ]; then
    echo "SKIP train size=$SIZE seed=$SEED"
else
    echo "=== train size=$SIZE seed=$SEED start $(date +%H:%M:%S)"
    PYTHONPATH=src "$PY" src/repair/run_sft.py \
        --base-model "$BASE" --model-revision "$REVISION" \
        --data-path "$ARMS/fuzzlang-${SIZE}.train.jsonl" \
        --adapter-out "$run/adapter" \
        --target-format window-rewrite \
        --epochs "$EPOCHS" --batch-size "$BATCH" --grad-accum "$GRAD_ACCUM" \
        --lr "$LR" --seed "$SEED" --max-seq-len "$MAX_SEQ_LEN" \
        --bf16 --local-files-only --no-gradient-checkpointing 2>&1 | tail -8 \
        || { echo "FAIL train size=$SIZE"; exit 1; }
    echo "=== train size=$SIZE done $(date +%H:%M:%S)"
fi

# Distinct C and C++ drivers: the unseen-project cohort is ~40% C, and compiling
# a .c file with clang++ produced a spurious failure in an earlier evaluation.
# TARGET_FORMAT must match training; the offset representation silently scores
# near zero.
for cohort in eval_unseen_tu heldout_project; do
    out="$EVAL/fuzzlang${SIZE}-seed${SEED}--${cohort}.json"
    if [ -s "$out" ]; then echo "SKIP eval $SIZE / $cohort"; continue; fi
    echo "=== eval size=$SIZE / $cohort start $(date +%H:%M:%S)"
    PYTHONPATH=src "$PY" src/repair/run_adapter_eval.py \
        --base-model "$BASE" --adapter "$run/adapter" \
        --data-path "$COHORTS/${cohort}.jsonl" \
        --clang-bin /p/lustre2/shan4/fuzzlang-clang/bin/clang++ \
        --clang-c-bin /p/lustre2/shan4/fuzzlang-clang/bin/clang \
        --diagtool-bin /p/lustre2/shan4/fuzzlang-clang/bin/diagtool \
        --out "$out" --max-instances "$MAX_INSTANCES" \
        --max-new-tokens "$MAX_NEW_TOKENS" --seed 42 \
        --target-format window-rewrite \
        --local-files-only 2>&1 | tail -5 || echo "FAIL eval $SIZE / $cohort"
done
echo "=== E5 TIER $SIZE DONE $(date +%H:%M:%S)"
