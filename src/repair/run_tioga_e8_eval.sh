#!/bin/bash
# E8 evaluation: serve Gemma-4-31B + the FuzzLang LoRA, then score both cohorts.
#
# Server and client share one allocation because the server has to be on the
# GPUs. vLLM shards with tensor parallelism, so this takes minutes where the
# in-process path in E7 took 3h17m per cohort on the same hardware.
set -uo pipefail
# The verifier compiles deliberately broken source, so Clang crashes are
# routine. Each crash dropped a core file into the working directory --
# 124 of them accumulated, all truncated to 16KB and useless for debugging.
ulimit -c 0

REPO=${REPO:-/p/lustre2/shan4/new-fuzzlang}
ADAPTER=${ADAPTER:-$REPO/.artifacts/sft-runs/e8-big/fuzzlang4000-31b-seed42/adapter}
LORA_NAME=${LORA_NAME:-gemma-4-31B-it-fuzzlang}
PORT=${PORT:-8000}
OUT=${OUT:-$REPO/.artifacts/sft-eval/e8-big}
COHORTS=${COHORTS:-$REPO/data/gen/experiments/e3-eval-cohorts-v0001}
MAX_INSTANCES=${MAX_INSTANCES:-150}
MAX_NEW_TOKENS=${MAX_NEW_TOKENS:-512}
# vLLM batches continuously; one request at a time leaves it idle between
# calls, which is the same waste as allocating eight GPUs to run one.
CONCURRENCY=${CONCURRENCY:-16}
# System python3, not the Gemma venv. With --backend vllm the client never
# loads a model, so torch and trl are unused, and the venv lacks the `openai`
# package the chat backend needs while the system interpreter has it.
# Installing into the shared venv to fix that would change state other work
# depends on.
PY=${PY:-python3}
SERVE_LOG=${SERVE_LOG:-$REPO/.artifacts/e8-logs/serve.out}

cd "$REPO"
mkdir -p "$OUT" "$(dirname "$SERVE_LOG")"

ADAPTER="$ADAPTER" LORA_NAME="$LORA_NAME" PORT="$PORT" \
    setsid bash src/repair/run_tioga_e8_serve_lora.sh > "$SERVE_LOG" 2>&1 &
SERVE_PID=$!
# The container keeps running after this script exits unless it is torn down.
trap 'kill -- -$SERVE_PID 2>/dev/null; pkill -f "vllm serve" 2>/dev/null' EXIT

echo "[e8-eval] waiting for the server (cold start compiles kernels; allow ~25 min)"
ready=0
for _ in $(seq 1 180); do
    if curl -sf "http://127.0.0.1:${PORT}/v1/models" >/dev/null 2>&1; then ready=1; break; fi
    if ! kill -0 "$SERVE_PID" 2>/dev/null; then
        echo "[e8-eval] server died during init; last 40 lines:"; tail -40 "$SERVE_LOG"; exit 1
    fi
    sleep 20
done
[ "$ready" -eq 1 ] || { echo "[e8-eval] server never became healthy"; tail -40 "$SERVE_LOG"; exit 1; }
echo "[e8-eval] server up; models advertised:"
curl -s "http://127.0.0.1:${PORT}/v1/models" | head -c 400; echo

for cohort in eval_unseen_tu heldout_project; do
    out="$OUT/fuzzlang4000-31b-seed42--${cohort}.json"
    if [ -s "$out" ]; then echo "SKIP $cohort"; continue; fi
    echo "=== eval $cohort start $(date +%H:%M:%S)"
    PYTHONPATH=src "$PY" src/repair/run_adapter_eval.py \
        --base-model "$ADAPTER" \
        --backend vllm --base-url "http://127.0.0.1:${PORT}/v1" \
        --served-model-name "$LORA_NAME" \
        --data-path "$COHORTS/${cohort}.jsonl" \
        --clang-bin /p/lustre2/shan4/fuzzlang-clang/bin/clang++ \
        --clang-c-bin /p/lustre2/shan4/fuzzlang-clang/bin/clang \
        --diagtool-bin /p/lustre2/shan4/fuzzlang-clang/bin/diagtool \
        --out "$out" --max-instances "$MAX_INSTANCES" \
        --max-new-tokens "$MAX_NEW_TOKENS" --seed 42 \
        --target-format window-rewrite --concurrency "$CONCURRENCY" \
        --local-files-only 2>&1 | tail -5 || echo "FAIL $cohort"
done
echo "=== E8 EVAL DONE $(date +%H:%M:%S)"
