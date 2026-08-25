#!/bin/bash
# E8: does FuzzLang data help a model that is already competent?
#
# E7 measured Gemma-4-31B zero-shot at 0.740 / 0.787 -- far above the 4B base it
# was previously compared against, and close to the 4B fine-tuned on 1,500
# records. That leaves the open question: is this data only useful for lifting a
# weak model to competence, or does it improve a model that already has it?
#
# Same 4,000-record arm the 4B was trained on, same epochs, learning rate,
# sequence length, and target format. Sharded with FSDP across the node's GPUs
# so every GPU trains -- `device_map=auto` would put one GPU to work and idle
# the rest, which is how the first E7 run wasted eight GPUs for one GPU's
# throughput.
#
# One hyperparameter cannot be matched and is reported rather than hidden: FSDP
# runs one process per GPU, so the smallest effective batch is the process
# count. The 4B used effective batch 2 (1 x grad-accum 2 on one GPU); this uses
# 8 (1 x grad-accum 1 across eight). Larger, not smaller, so it is not an
# advantage handed to the 31B on step count.
set -uo pipefail

REPO=${REPO:-/p/lustre2/shan4/new-fuzzlang}
BIG=${BIG:-/p/lustre1/shan4/gemma/hf/hub/models--google--gemma-4-31B-it/snapshots/518276fb130dc81caf9a4f772e65e63ef2526493}
ARM=${ARM:-$REPO/.artifacts/sft-arms/e5-scaling-seed42/fuzzlang-4000.train.jsonl}
OUT=${OUT:-$REPO/.artifacts/sft-runs/e8-big/fuzzlang4000-31b-seed42}
# 4 ranks, not 8. Each rank materialises the checkpoint on the host before
# sharding, and 8 x 62GB exceeds the node's 503GB -- the previous attempt died
# with SIGKILL from the OOM killer. Four also brings the effective batch (4)
# closer to the 4B run's 2, so the comparison improves rather than degrades.
NPROC=${NPROC:-4}
# FSDP2 fails here: accelerate's fsdp2_load_full_state_dict reads
# `sharded_param.device_mesh`, but with a LoRA-wrapped model some parameters
# arrive as plain Tensors rather than DTensors, so the attribute is absent.
# FSDP1 takes the older full-state-dict path and does not make that assumption.
FSDP_VERSION=${FSDP_VERSION:-1}
EPOCHS=${EPOCHS:-3}
BATCH=${BATCH:-1}
GRAD_ACCUM=${GRAD_ACCUM:-1}
LR=${LR:-2e-4}
MAX_SEQ_LEN=${MAX_SEQ_LEN:-1024}
SEED=${SEED:-42}
PY=${PY:-/p/lustre1/shan4/gemma/venv/bin/python}
TORCHRUN=${TORCHRUN:-/p/lustre1/shan4/gemma/venv/bin/torchrun}

cd "$REPO"
mkdir -p "$OUT"
export HF_HOME=${HF_HOME:-/p/lustre1/shan4/gemma/hf}
# FSDP shards parameters; each rank still materialises its shard on its own GPU.
export PYTORCH_ALLOC_CONF=${PYTORCH_ALLOC_CONF:-expandable_segments:True}
export TOKENIZERS_PARALLELISM=false
# peft resolves the FSDP wrap policy itself and reads this environment
# variable, not the trainer's fsdp_config. Without it peft falls back to the
# model's _no_split_modules, which for Gemma-4 lists Gemma4AudioLayer -- a
# class this checkpoint never instantiates -- and the lookup raises
# "Could not find the transformer layer class to wrap in the model."
# Wrapping only the text decoder is also what we want: the LoRA is text-only.
export FSDP_TRANSFORMER_CLS_TO_WRAP=${FSDP_TRANSFORMER_CLS_TO_WRAP:-Gemma4TextDecoderLayer}
# transformers gates rank-0-only checkpoint loading on BOTH of these being
# true, and sets them while constructing TrainingArguments -- too late if the
# model is built first. Setting them here removes the ordering dependency.
export ACCELERATE_USE_FSDP=${ACCELERATE_USE_FSDP:-1}
export FSDP_CPU_RAM_EFFICIENT_LOADING=${FSDP_CPU_RAM_EFFICIENT_LOADING:-1}

if [ -s "$OUT/adapter/run-manifest.json" ]; then
    echo "SKIP train: adapter already present"
    exit 0
fi

echo "=== 31B LoRA start $(date) : $NPROC ranks, arm $(basename "$ARM")"
PYTHONPATH=src "$TORCHRUN" --nproc-per-node="$NPROC" --nnodes=1 \
    src/repair/run_sft.py \
    --base-model "$BIG" \
    --data-path "$ARM" \
    --adapter-out "$OUT/adapter" \
    --target-format window-rewrite \
    --fsdp --fsdp-version "$FSDP_VERSION" \
    --fsdp-transformer-layer Gemma4TextDecoderLayer \
    --epochs "$EPOCHS" --batch-size "$BATCH" --grad-accum "$GRAD_ACCUM" \
    --lr "$LR" --seed "$SEED" --max-seq-len "$MAX_SEQ_LEN" \
    --bf16 --local-files-only > "$OUT/train.log" 2>&1
status=$?
# Keep the whole log. torchrun prints its failure summary last, so piping
# straight into `tail` discards the rank-0 traceback that actually says why.
tail -30 "$OUT/train.log"
[ "$status" -eq 0 ] || { echo "FAILED (rc=$status); full log at $OUT/train.log"; exit "$status"; }
echo "=== 31B LoRA done $(date)"
