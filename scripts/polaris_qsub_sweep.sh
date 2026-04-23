#!/bin/bash
#PBS -N dvcr_sweep
#PBS -A diomp
#PBS -q prod
#PBS -l select=1:system=polaris
#PBS -l walltime=12:00:00
#PBS -l filesystems=home:eagle
#PBS -j oe
#PBS -o /lus/eagle/projects/diomp/baodi/Fuzzlang/logs/sweep.out
#
# Main inference sweep (one method × one seed per job; submit 12 jobs for the
# 4-row main table × 3 seeds, or use an array job).
#
# Strategy: run a single vLLM server bound to one A100 per job, feed the
# eval split through the DVCR harness, write a JSON result file.
#
# Submit with:
#   qsub -v METHOD=dvcr,SEED=17 scripts/polaris_qsub_sweep.sh
#   qsub -v METHOD=b0_zero_shot,SEED=17 scripts/polaris_qsub_sweep.sh
#   qsub -v METHOD=dvcr_no_id,SEED=42 scripts/polaris_qsub_sweep.sh
#
# Budget per job: ~2 node-hours for DVCR at 3000 instances × T=5 × K=4 on 7B.
# 12 jobs × ~2 hours = ~25 node-hours total for the main table.

set -euo pipefail
cd "${PBS_O_WORKDIR:-/lus/eagle/projects/diomp/baodi/Fuzzlang}"
mkdir -p logs results

# shellcheck source=/dev/null
source scripts/activate_dvcr.sh

METHOD="${METHOD:?must be one of b0_zero_shot,b1_stderr_loop,b2_static_sft,b3_sft_stderr_loop,dvcr,dvcr_no_id,dvcr_no_structure,dvcr_no_loop}"
SEED="${SEED:?must specify seed (int)}"
SPLIT="${SPLIT:-/lus/eagle/projects/diomp/baodi/Fuzzlang/data/natErr/main.jsonl}"
MODEL="${MODEL:-/lus/eagle/projects/diomp/baodi/softwares/models/hf-cache/hub/models--Qwen--Qwen2.5-Coder-7B-Instruct}"
ADAPTER="${ADAPTER:-}"   # set for B2/B3 (LoRA SFT adapter path)
T="${T:-5}"
K="${K:-4}"
TOKEN_ENVELOPE="${TOKEN_ENVELOPE:-5120}"
VLLM_PORT="${VLLM_PORT:-8000}"

STAMP="$(date +%Y%m%d_%H%M%S)_${METHOD}_s${SEED}"
RESULT_OUT="results/${STAMP}.json"

echo "[sweep] $STAMP on $(hostname) | method=$METHOD seed=$SEED T=$T K=$K split=$SPLIT"
nvidia-smi --query-gpu=index,name,memory.free --format=csv

export CUDA_VISIBLE_DEVICES=0
export TOKENIZERS_PARALLELISM=false

# 1. Start vLLM server in background.
echo "[sweep] launching vLLM server on port $VLLM_PORT"
ARGS=(--model "$MODEL" --host 127.0.0.1 --port "$VLLM_PORT"
      --max-model-len 8192 --dtype bfloat16 --gpu-memory-utilization 0.85
      --disable-log-requests)
if [ -n "$ADAPTER" ]; then
    ARGS+=(--enable-lora --lora-modules "sft=$ADAPTER" --max-lora-rank 16)
fi
python -m vllm.entrypoints.openai.api_server "${ARGS[@]}" \
    > "logs/vllm_${STAMP}.log" 2>&1 &
VLLM_PID=$!
trap "kill -9 $VLLM_PID 2>/dev/null || true" EXIT

# Wait for vLLM to be ready.
for i in $(seq 1 120); do
    if curl -sf "http://127.0.0.1:$VLLM_PORT/health" >/dev/null 2>&1; then
        echo "[sweep] vLLM ready after ${i}s"
        break
    fi
    sleep 2
done

# 2. Run the eval harness.
python scripts/run_sweep.py \
    --method "$METHOD" \
    --seed "$SEED" \
    --split "$SPLIT" \
    --model-name "$(basename "$MODEL")" \
    --base-url "http://127.0.0.1:$VLLM_PORT/v1" \
    --T "$T" --K "$K" \
    --token-envelope "$TOKEN_ENVELOPE" \
    --clang-bin "$FUZZLANG_CLANG_BIN" \
    --diagtool-bin "$FUZZLANG_DIAGTOOL_BIN" \
    ${ADAPTER:+--adapter-name sft} \
    --out "$RESULT_OUT" \
    2>&1 | tee "logs/sweep_${STAMP}.log"

echo "[sweep] done at $(date -Iseconds), results in $RESULT_OUT"
