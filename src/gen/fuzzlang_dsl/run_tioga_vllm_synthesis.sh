#!/bin/bash
# One Tioga node only: vLLM TP=8 occupies all 8 logical GPUs, while the
# host-side client submits a bounded stream of Injector-synthesis requests to
# 127.0.0.1.  This script must run inside an existing one-node Flux allocation.
set -euo pipefail
ulimit -c 0

: "${REQUESTS:?set REQUESTS to the synthesis-request JSONL}"
: "${OUTPUT_DIR:?set OUTPUT_DIR to the campaign output directory}"

REPO=/p/lustre2/shan4/new-fuzzlang
GEMMA=/p/lustre1/shan4/gemma
PORT="${PORT:-8000}"
REQUEST_BATCH_SIZE="${REQUEST_BATCH_SIZE:-64}"
VLLM_CONCURRENCY="${VLLM_CONCURRENCY:-64}"
MAX_TOKENS="${MAX_TOKENS:-600}"
CANDIDATES="${CANDIDATES:-2}"
FEEDBACK_ROUNDS="${FEEDBACK_ROUNDS:-2}"
SYNTHESIS_MODE="${SYNTHESIS_MODE:-lexical}"
REQUEST_START="${REQUEST_START:-0}"
REQUEST_STOP="${REQUEST_STOP:-}"
RESUME="${RESUME:-0}"
# Most direct-Injector waves are deliberately test-evidenced.  A separate
# compiler-emission-only long-tail wave may opt out, but must do so explicitly;
# the default remains the stricter test-evidence gate.
REQUIRE_REGRESSION_EVIDENCE="${REQUIRE_REGRESSION_EVIDENCE:-1}"

# Direct-DSL shards are resumable but their individual output directory has
# one atomic checkpoint stream; never allow two jobs to write it concurrently.
mkdir -p "$OUTPUT_DIR"
exec 9>"$OUTPUT_DIR/.fuzzlang-writer.lock"
if ! flock -n 9; then
    echo "another FuzzLang writer owns $OUTPUT_DIR" >&2
    exit 75
fi

cleanup() {
    if [[ -n "${SERVE_PID:-}" ]]; then
        # The container launcher creates descendants (podman, vLLM, TP
        # workers).  It must be its own process group so a completed synthesis
        # run cannot retain a node while only the container is still alive.
        # The inner launcher may ignore TERM while shutting down; bound that
        # wait and escalate to KILL so an already-complete campaign cannot
        # strand its sole 8-GPU node.
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
        # A container launcher may keep its parent shell blocked after the
        # server process group is gone. cleanup must not block waiting for the container launcher;
        # Flux will reap the allocation cgroup.
    fi
}
trap cleanup EXIT INT TERM

# This is the existing, tested TP=8 container launcher.  It runs the server
# in this allocation and exposes it only on this node's loopback interface.
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
RANGE_ARGS=(--request-start "$REQUEST_START")
if [[ -n "$REQUEST_STOP" ]]; then
    RANGE_ARGS+=(--request-stop "$REQUEST_STOP")
fi
RESUME_ARGS=()
if [[ "$RESUME" == "1" ]]; then
    RESUME_ARGS+=(--resume)
fi
EVIDENCE_ARGS=()
if [[ "$REQUIRE_REGRESSION_EVIDENCE" == "1" ]]; then
    EVIDENCE_ARGS+=(--require-regression-test-evidence)
elif [[ "$REQUIRE_REGRESSION_EVIDENCE" != "0" ]]; then
    echo "REQUIRE_REGRESSION_EVIDENCE must be 0 or 1" >&2
    exit 2
fi
# Treat only a manifest newer than this invocation as durable completion.  The
# output directory may be resumed, so an older manifest must never stop a
# still-useful synthesis range.
RUN_MARKER="$OUTPUT_DIR/.fuzzlang-run-start"
touch "$RUN_MARKER"
PYTHONPATH=src "$GEMMA/venv/bin/python" src/gen/fuzzlang_dsl/run_local_synthesis.py \
    --backend vllm --base-url "http://127.0.0.1:${PORT}/v1" \
    --vllm-concurrency "$VLLM_CONCURRENCY" \
    --requests "$REQUESTS" --output-dir "$OUTPUT_DIR" \
    --request-batch-size "$REQUEST_BATCH_SIZE" --candidates "$CANDIDATES" \
    --feedback-rounds "$FEEDBACK_ROUNDS" --max-tokens "$MAX_TOKENS" \
    --synthesis-mode "$SYNTHESIS_MODE" \
    "${RANGE_ARGS[@]}" "${RESUME_ARGS[@]}" \
    "${EVIDENCE_ARGS[@]}" &
RUN_PID=$!

# A vLLM client can leave its worker threads alive after all artifacts and the
# manifest have been written.  Reclaim the node deterministically; the EXIT
# trap then terminates the server process group.
while kill -0 "$RUN_PID" 2>/dev/null; do
    if [[ -s "$OUTPUT_DIR/manifest.json" && "$OUTPUT_DIR/manifest.json" -nt "$RUN_MARKER" ]]; then
        for _ in $(seq 1 5); do
            kill -0 "$RUN_PID" 2>/dev/null || break
            sleep 1
        done
        if kill -0 "$RUN_PID" 2>/dev/null; then
            kill -TERM "$RUN_PID" 2>/dev/null || true
            sleep 2
            kill -0 "$RUN_PID" 2>/dev/null && kill -KILL "$RUN_PID" 2>/dev/null || true
        fi
        break
    fi
    sleep 1
done

RUN_RC=0
wait "$RUN_PID" || RUN_RC=$?
if (( RUN_RC != 0 )) && [[ ! -s "$OUTPUT_DIR/manifest.json" || ! "$OUTPUT_DIR/manifest.json" -nt "$RUN_MARKER" ]]; then
    exit "$RUN_RC"
fi
