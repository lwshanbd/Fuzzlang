#!/bin/bash
# E3 DirectEdit data arm: one local-Gemma localized edit per (diagnostic, source),
# compiler-verified.  One Tioga node, one TP=8 vLLM server, compilers alongside.
set -euo pipefail
ulimit -c 0
: "${REQUESTS:?}"; : "${OUTPUT_DIR:?}"
REPO=/p/lustre2/shan4/new-fuzzlang
GEMMA=/p/lustre1/shan4/gemma
PORT="${PORT:-8000}"
mkdir -p "$OUTPUT_DIR"
cleanup() {
    if [[ -n "${SERVE_PID:-}" ]]; then
        kill -TERM -- "-$SERVE_PID" 2>/dev/null || true
        kill -TERM "$SERVE_PID" 2>/dev/null || true
        for _ in $(seq 1 20); do kill -0 "$SERVE_PID" 2>/dev/null || break; sleep 1; done
        kill -KILL -- "-$SERVE_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM
SELFTEST=0 PORT="$PORT" EAGER="${EAGER:-1}" setsid bash "$GEMMA/run/_vllm_serve_inner.sh" &
SERVE_PID=$!
for _ in $(seq 1 360); do
    kill -0 "$SERVE_PID" 2>/dev/null || { wait "$SERVE_PID"; exit 1; }
    "$GEMMA/venv/bin/python" -c \
      "import urllib.request;urllib.request.urlopen('http://127.0.0.1:${PORT}/health',timeout=2)" \
      >/dev/null 2>&1 && break
    sleep 5
done
cd "$REPO"
PYTHONPATH=src "$GEMMA/venv/bin/python" src/gen/fuzzlang_dsl/run_e1_experiment.py \
    --requests "$REQUESTS" --output-dir "$OUTPUT_DIR" \
    --clang-bin /p/lustre2/shan4/fuzzlang-clang/bin/clang++ \
    --clang-c-bin /p/lustre2/shan4/fuzzlang-clang/bin/clang \
    --diagtool-bin /p/lustre2/shan4/fuzzlang-clang/bin/diagtool \
    --backend vllm --base-url "http://127.0.0.1:${PORT}/v1" --vllm-concurrency 24 \
    --arm direct_edit --candidates "${CANDIDATES:-4}" --temperature "${TEMPERATURE:-0.5}" \
    --max-workers "${MAX_WORKERS:-12}" --verify-timeout 90 \
    --primary-project llvm --seed "${SEED:-20260808}" &
RUN_PID=$!
RUN_MARKER="$OUTPUT_DIR/.e3-start"; touch "$RUN_MARKER"
while kill -0 "$RUN_PID" 2>/dev/null; do
    if [[ -s "$OUTPUT_DIR/comparison.json" && "$OUTPUT_DIR/comparison.json" -nt "$RUN_MARKER" ]]; then
        for _ in $(seq 1 10); do kill -0 "$RUN_PID" 2>/dev/null || break; sleep 1; done
        kill -TERM "$RUN_PID" 2>/dev/null || true; break
    fi
    sleep 5
done
RUN_RC=0; wait "$RUN_PID" || RUN_RC=$?
[[ -s "$OUTPUT_DIR/comparison.json" ]] || exit "$RUN_RC"
echo "=== E3 DIRECTEDIT DONE ==="
