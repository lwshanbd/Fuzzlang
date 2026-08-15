#!/bin/bash
# E3: train every matched construction arm at every seed on one Tioga node.
#
# The arms already agree on record count and rendered tokens, so holding epochs,
# batch size, and gradient accumulation fixed across arms also equalises the
# optimizer-update count -- the comparison is then about the data, not the
# budget.  Activation checkpointing stays off: ROCm recomputation failed on
# variable-length batches in the earlier pilot and that choice is archived.
set -uo pipefail

REPO=${REPO:-/p/lustre2/shan4/new-fuzzlang}
ARMS=${ARMS:-$REPO/.artifacts/sft-arms/e3-v0002-multiproject-seed42}
OUT=${OUT:-$REPO/.artifacts/sft-runs/e3-v0002}
BASE=${BASE:-$REPO/.artifacts/models/gemma-3-4b-it}
REVISION=${REVISION:-093f9f388b31de276ce2de164bdc2081324b9767}
SEEDS=${SEEDS:-"42 1337 20260808"}
EPOCHS=${EPOCHS:-3}
BATCH=${BATCH:-1}
GRAD_ACCUM=${GRAD_ACCUM:-2}
LR=${LR:-2e-4}
MAX_SEQ_LEN=${MAX_SEQ_LEN:-1024}
# The pinned training stack (peft 0.18.1 / trl 0.27.2 / torch 2.9.1+rocm6.4)
# lives in the Gemma venv; the system interpreter has none of it.
PY=${PY:-/p/lustre1/shan4/gemma/venv/bin/python}

cd "$REPO"
mkdir -p "$OUT"
for arm in mechanical direct_edit fuzzlang; do
    for seed in $SEEDS; do
        run="$OUT/${arm}-seed${seed}"
        if [ -s "$run/adapter/run-manifest.json" ]; then
            echo "SKIP $arm seed=$seed"; continue
        fi
        echo "=== train $arm seed=$seed"
        PYTHONPATH=src "$PY" src/repair/run_sft.py \
            --base-model "$BASE" --model-revision "$REVISION" \
            --data-path "$ARMS/${arm}.train.jsonl" \
            --adapter-out "$run/adapter" \
            --target-format window-rewrite \
            --epochs "$EPOCHS" --batch-size "$BATCH" --grad-accum "$GRAD_ACCUM" \
            --lr "$LR" --seed "$seed" --max-seq-len "$MAX_SEQ_LEN" \
            --bf16 --local-files-only --no-gradient-checkpointing 2>&1 | tail -12 \
            || echo "FAIL $arm seed=$seed"
    done
done
echo "=== E3 TRAINING DONE ==="
