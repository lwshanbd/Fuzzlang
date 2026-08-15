#!/bin/bash
# E5: does more FuzzLang data keep helping?
#
# E3 matched every arm to 557 records because that is what the most expensive
# arm (DirectEdit, one model call per record) could reach.  FuzzLang can supply
# an order of magnitude more at no extra cost, so that comparison is a lower
# bound.  This trains the *same* arm at nested sizes under identical
# hyperparameters; 3 epochs over more data means more optimizer steps, which is
# the effect being measured, not a confound.
set -uo pipefail

REPO=${REPO:-/p/lustre2/shan4/new-fuzzlang}
ARMS=${ARMS:-$REPO/.artifacts/sft-arms/e5-scaling-seed42}
OUT=${OUT:-$REPO/.artifacts/sft-runs/e5-scaling}
BASE=${BASE:-$REPO/.artifacts/models/gemma-3-4b-it}
REVISION=${REVISION:-093f9f388b31de276ce2de164bdc2081324b9767}
SIZES=${SIZES:-"557 1500 4000"}
SEEDS=${SEEDS:-"42"}
EPOCHS=${EPOCHS:-3}
BATCH=${BATCH:-1}
GRAD_ACCUM=${GRAD_ACCUM:-2}
LR=${LR:-2e-4}
MAX_SEQ_LEN=${MAX_SEQ_LEN:-1024}
# Same pinned stack as E3 (peft 0.18.1 / trl 0.27.2 / torch 2.9.1+rocm6.4).
PY=${PY:-/p/lustre1/shan4/gemma/venv/bin/python}

cd "$REPO"
mkdir -p "$OUT"
for size in $SIZES; do
    for seed in $SEEDS; do
        run="$OUT/fuzzlang${size}-seed${seed}"
        if [ -s "$run/adapter/run-manifest.json" ]; then
            echo "SKIP size=$size seed=$seed"; continue
        fi
        echo "=== train size=$size seed=$seed at $(date +%H:%M:%S)"
        PYTHONPATH=src "$PY" src/repair/run_sft.py \
            --base-model "$BASE" --model-revision "$REVISION" \
            --data-path "$ARMS/fuzzlang-${size}.train.jsonl" \
            --adapter-out "$run/adapter" \
            --target-format window-rewrite \
            --epochs "$EPOCHS" --batch-size "$BATCH" --grad-accum "$GRAD_ACCUM" \
            --lr "$LR" --seed "$seed" --max-seq-len "$MAX_SEQ_LEN" \
            --bf16 --local-files-only --no-gradient-checkpointing 2>&1 | tail -8 \
            || echo "FAIL size=$size seed=$seed"
    done
done
echo "=== E5 TRAINING DONE at $(date +%H:%M:%S) ==="
for d in "$OUT"/*/adapter; do
    [ -s "$d/run-manifest.json" ] || continue
    python3 -c "
import json,sys
m=json.load(open('$d/run-manifest.json'))
print(f\"  {'$d'.split('/')[-2]:24} loss={m.get('final_loss','?')} tokens={m.get('total_tokens','?')}\")"
done
