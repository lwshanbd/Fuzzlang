#!/bin/bash
#PBS -N fuzzlang_sft
#PBS -A diomp
#PBS -q prod
#PBS -l select=1:system=polaris
#PBS -l walltime=04:00:00
#PBS -l filesystems=home:eagle
#PBS -j oe
#PBS -o /lus/eagle/projects/diomp/baodi/Fuzzlang/logs/sft.out
#
# B2 LoRA SFT: Qwen2.5-Coder-7B-Instruct fine-tuned on Fuzzlang-LLVM
# (buggy, error, fixed) triples. Produces a LoRA adapter at:
#   $ADAPTER_OUT
# which the B2 runner loads at inference time.
#
# Submit with:
#   qsub scripts/polaris_qsub_sft.sh
# or override the default config:
#   qsub -v CONFIG=configs/sft_alt.yaml scripts/polaris_qsub_sft.sh
#
# Budget: ~8 node-hours for a single LoRA run at rank 16, 1 epoch over ~50k
# filtered triples. Matches the compute budget in EXPERIMENT_PLAN.md (~30
# GPU-hrs on Qwen2.5-Coder-7B).

set -euo pipefail
cd "${PBS_O_WORKDIR:-/lus/eagle/projects/diomp/baodi/Fuzzlang}"
mkdir -p logs

# shellcheck source=/dev/null
source scripts/activate_diag.sh

# Override via -v:
CONFIG="${CONFIG:-configs/sft_default.yaml}"
ADAPTER_OUT="${ADAPTER_OUT:-/lus/eagle/projects/diomp/baodi/softwares/adapters/b2_qwen7b_fuzzlang_lora}"
DATA_PATH="${DATA_PATH:-/lus/eagle/projects/diomp/baodi/Fuzzlang/data/fuzzlang-llvm/train.jsonl}"
BASE_MODEL="${BASE_MODEL:-/lus/eagle/projects/diomp/baodi/softwares/models/hf-cache/hub/models--Qwen--Qwen2.5-Coder-7B-Instruct}"

echo "[sft] node: $(hostname) | date: $(date -Iseconds)"
echo "[sft] config=$CONFIG  out=$ADAPTER_OUT"
nvidia-smi --query-gpu=index,name,memory.total --format=csv

export CUDA_VISIBLE_DEVICES=0,1,2,3
export TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=8

python scripts/run_sft.py \
    --base-model "$BASE_MODEL" \
    --data-path "$DATA_PATH" \
    --adapter-out "$ADAPTER_OUT" \
    --lora-rank 16 \
    --epochs 1 \
    --batch-size 8 \
    --grad-accum 4 \
    --lr 2e-4 \
    --bf16 \
    --seed 42 \
    2>&1 | tee logs/sft_$(date +%Y%m%d_%H%M%S).log

echo "[sft] done at $(date -Iseconds)"
