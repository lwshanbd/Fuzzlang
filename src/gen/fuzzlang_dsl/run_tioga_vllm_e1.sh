#!/bin/bash
# One Tioga node only: one vLLM server uses all 8 logical GPUs (TP=8) while the
# compiler verification for both E1 arms runs on that same node's CPUs.  Do not
# launch this script per rank, and do not launch a second copy against the same
# OUTPUT_DIR.
set -euo pipefail
ulimit -c 0

: "${REQUESTS:?set REQUESTS to the frozen E1 request JSONL}"
: "${OUTPUT_DIR:?set OUTPUT_DIR to the E1 run directory}"

REPO=/p/lustre2/shan4/new-fuzzlang
GEMMA=/p/lustre1/shan4/gemma
PORT="${PORT:-8000}"
ARM="${ARM:-both}"
CANDIDATES="${CANDIDATES:-4}"
TEMPERATURE="${TEMPERATURE:-0.5}"
DIRECT_EDIT_MAX_TOKENS="${DIRECT_EDIT_MAX_TOKENS:-400}"
INJECTOR_MAX_TOKENS="${INJECTOR_MAX_TOKENS:-1200}"
EVIDENCE_SOURCES="${EVIDENCE_SOURCES:-2}"
PRIMARY_PROJECT="${PRIMARY_PROJECT:-llvm}"
MAX_WORKERS="${MAX_WORKERS:-12}"
VLLM_CONCURRENCY="${VLLM_CONCURRENCY:-32}"
VERIFY_TIMEOUT="${VERIFY_TIMEOUT:-30}"
SEED="${SEED:-20260807}"
EXTRA_ARGS=()
if [[ -n "${SOURCES_PER_TARGET:-}" ]]; then
    EXTRA_ARGS+=(--sources-per-target "$SOURCES_PER_TARGET")
fi
if [[ -n "${TARGET_LIMIT:-}" ]]; then
    EXTRA_ARGS+=(--target-limit "$TARGET_LIMIT")
fi

mkdir -p "$OUTPUT_DIR"
exec 9>"$OUTPUT_DIR/.fuzzlang-e1.lock"
if ! flock -n 9; then
    echo "another E1 run owns $OUTPUT_DIR" >&2
    exit 75
fi

cleanup() {
    if [[ -n "${SERVE_PID:-}" ]]; then
        kill -TERM -- "-$SERVE_PID" 2>/dev/null || true
        kill -TERM "$SERVE_PID" 2>/dev/null || true
        for _ in $(seq 1 20); do
            kill -0 "$SERVE_PID" 2>/dev/null || break
            sleep 1
        done
        if kill -0 "$SERVE_PID" 2>/dev/null; then
            kill -KILL -- "-$SERVE_PID" 2>/dev/null || true
            kill -KILL "$SERVE_PID" 2>/dev/null || true
        fi
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
PYTHONPATH=src "$GEMMA/venv/bin/python" src/gen/fuzzlang_dsl/run_e1_experiment.py \
    --requests "$REQUESTS" \
    --output-dir "$OUTPUT_DIR" \
    --clang-bin /p/lustre2/shan4/fuzzlang-clang/bin/clang++ \
    --clang-c-bin /p/lustre2/shan4/fuzzlang-clang/bin/clang \
    --diagtool-bin /p/lustre2/shan4/fuzzlang-clang/bin/diagtool \
    --backend vllm --base-url "http://127.0.0.1:${PORT}/v1" \
    --vllm-concurrency "$VLLM_CONCURRENCY" \
    --arm "$ARM" --candidates "$CANDIDATES" --temperature "$TEMPERATURE" \
    --direct-edit-max-tokens "$DIRECT_EDIT_MAX_TOKENS" \
    --injector-max-tokens "$INJECTOR_MAX_TOKENS" \
    --evidence-sources "$EVIDENCE_SOURCES" \
    --primary-project "$PRIMARY_PROJECT" \
    --max-workers "$MAX_WORKERS" --verify-timeout "$VERIFY_TIMEOUT" \
    --seed "$SEED" "${EXTRA_ARGS[@]}" &
RUN_PID=$!

# Do not strand the GPU allocation: once comparison.json is on disk the run is
# complete, so give the HTTP client a brief grace period and then stop it.
RUN_MARKER="$OUTPUT_DIR/.fuzzlang-e1-start"
touch "$RUN_MARKER"
while kill -0 "$RUN_PID" 2>/dev/null; do
    if [[ -s "$OUTPUT_DIR/comparison.json" && "$OUTPUT_DIR/comparison.json" -nt "$RUN_MARKER" ]]; then
        for _ in $(seq 1 10); do
            kill -0 "$RUN_PID" 2>/dev/null || break
            sleep 1
        done
        kill -0 "$RUN_PID" 2>/dev/null && kill -TERM "$RUN_PID" 2>/dev/null || true
        break
    fi
    sleep 2
done

RUN_RC=0
wait "$RUN_PID" || RUN_RC=$?
if (( RUN_RC != 0 )) && [[ ! -s "$OUTPUT_DIR/comparison.json" ]]; then
    exit "$RUN_RC"
fi
