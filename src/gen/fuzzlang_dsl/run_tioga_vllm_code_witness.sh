#!/bin/bash
# One Tioga node only: one vLLM server uses all 8 logical GPUs (TP=8), while
# compiler gating runs on that same node.  Do not launch this script per rank.
set -euo pipefail
ulimit -c 0

: "${REQUESTS:?set REQUESTS to the code-witness request JSONL}"
: "${OUTPUT_DIR:?set OUTPUT_DIR to the campaign output directory}"

REPO=/p/lustre2/shan4/new-fuzzlang
GEMMA=/p/lustre1/shan4/gemma
PORT="${PORT:-8000}"
REQUEST_BATCH_SIZE="${REQUEST_BATCH_SIZE:-64}"
VLLM_CONCURRENCY="${VLLM_CONCURRENCY:-64}"
CANDIDATES="${CANDIDATES:-8}"
FEEDBACK_ROUNDS="${FEEDBACK_ROUNDS:-2}"
MAX_TOKENS="${MAX_TOKENS:-400}"
ALLOW_DIRECTIVE_FRAGMENTS="${ALLOW_DIRECTIVE_FRAGMENTS:-0}"

cleanup() {
    if [[ -n "${SERVE_PID:-}" ]]; then
        kill -TERM -- "-$SERVE_PID" 2>/dev/null || true
        for _ in $(seq 1 20); do
            kill -0 "$SERVE_PID" 2>/dev/null || break
            sleep 1
        done
        if kill -0 "$SERVE_PID" 2>/dev/null; then
            kill -KILL -- "-$SERVE_PID" 2>/dev/null || true
        fi
        wait "$SERVE_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

SELFTEST=0 PORT="$PORT" EAGER="${EAGER:-0}" \
    setsid bash "$GEMMA/run/_vllm_serve_inner.sh" &
SERVE_PID=$!

for _ in $(seq 1 360); do
    if ! kill -0 "$SERVE_PID" 2>/dev/null; then
        wait "$SERVE_PID"
        exit 1
    fi
    if "$GEMMA/venv/bin/python" -c \
        "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${PORT}/health', timeout=2)" \
        >/dev/null 2>&1; then
        break
    fi
    sleep 5
done

"$GEMMA/venv/bin/python" -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${PORT}/health', timeout=2)" \
    >/dev/null

cd "$REPO"
DIRECTIVE_ARGS=()
if [[ "$ALLOW_DIRECTIVE_FRAGMENTS" == "1" ]]; then
    DIRECTIVE_ARGS+=(--allow-preprocessor-directives)
fi
PYTHONPATH=src "$GEMMA/venv/bin/python" src/gen/fuzzlang_dsl/run_local_code_witness.py \
    --backend vllm --base-url "http://127.0.0.1:${PORT}/v1" \
    --vllm-concurrency "$VLLM_CONCURRENCY" \
    --requests "$REQUESTS" \
    --clang-bin /p/lustre2/shan4/fuzzlang-clang/bin/clang++ \
    --clang-c-bin /p/lustre2/shan4/fuzzlang-clang/bin/clang \
    --diagtool-bin /p/lustre2/shan4/fuzzlang-clang/bin/diagtool \
    --output-dir "$OUTPUT_DIR" \
    --candidates "$CANDIDATES" --feedback-rounds "$FEEDBACK_ROUNDS" \
    --request-batch-size "$REQUEST_BATCH_SIZE" --max-tokens "$MAX_TOKENS" \
    --witness-mode append --regression-evidence --no-admit-observed-errors \
    "${DIRECTIVE_ARGS[@]}"
