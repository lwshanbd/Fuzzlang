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
TEMPERATURE="${TEMPERATURE:-0.5}"
# A production LLVM translation unit can legitimately take longer than the
# runner's five-second library default on a cold compiler cache.  Treating
# that as an unclean parent silently discards a valid real-source witness.
VERIFY_TIMEOUT="${VERIFY_TIMEOUT:-20}"
ALLOW_DIRECTIVE_FRAGMENTS="${ALLOW_DIRECTIVE_FRAGMENTS:-0}"
WITNESS_MODE="${WITNESS_MODE:-append}"
RESUME="${RESUME:-0}"
REGRESSION_EVIDENCE="${REGRESSION_EVIDENCE:-1}"

# Checkpoints are atomically replaced, not mergeable.  A second writer would
# otherwise race a resumed slice and silently lose accepted Injector rows.
mkdir -p "$OUTPUT_DIR"
exec 9>"$OUTPUT_DIR/.fuzzlang-writer.lock"
if ! flock -n 9; then
    echo "another FuzzLang writer owns $OUTPUT_DIR" >&2
    exit 75
fi

if [[ "$WITNESS_MODE" != "append" && "$WITNESS_MODE" != "replace" ]]; then
    echo "WITNESS_MODE must be append or replace" >&2
    exit 2
fi

cleanup() {
    if [[ -n "${SERVE_PID:-}" ]]; then
        # ``setsid`` normally makes the launcher a new process-group leader,
        # but some container launchers retain the wrapper PID outside that
        # group.  Signal both forms so a completed generation run cannot hold
        # a GPU allocation until Flux's wall-time limit.
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
        # The container launcher can keep its parent shell in an
        # uninterruptible wait even after the vLLM process group was killed.
        # cleanup must not block waiting for the container launcher: returning
        # lets Flux reap the allocation cgroup and releases the GPU node.
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
RESUME_ARGS=()
if [[ "$RESUME" == "1" ]]; then
    RESUME_ARGS+=(--resume)
fi
REGRESSION_EVIDENCE_ARGS=(--regression-evidence)
if [[ "$REGRESSION_EVIDENCE" == "0" ]]; then
    REGRESSION_EVIDENCE_ARGS=(--no-regression-evidence)
fi
OBSERVED_ERROR_ARGS=(--no-admit-observed-errors)
if [[ "${ADMIT_OBSERVED_ERRORS:-0}" == "1" ]]; then
    # A separately labelled breadth campaign may retain an unintended primary
    # diagnostic, but only after it is distilled to an Injector and replayed
    # with an exact typed DiagID.  Target-focused campaigns preserve their
    # historical behaviour by default.
    OBSERVED_ERROR_ARGS=(--admit-observed-errors)
fi
# A resumed campaign may already have a manifest from its preceding slice.  A
# marker makes the completion watchdog act only on a manifest written by this
# invocation, after every record/Injector checkpoint is durable.
RUN_MARKER="$OUTPUT_DIR/.fuzzlang-run-start"
touch "$RUN_MARKER"
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
    --temperature "$TEMPERATURE" --timeout "${VERIFY_TIMEOUT:-20}" \
    --witness-mode "$WITNESS_MODE" "${OBSERVED_ERROR_ARGS[@]}" \
    "${DIRECTIVE_ARGS[@]}" "${RESUME_ARGS[@]}" \
    "${REGRESSION_EVIDENCE_ARGS[@]}" &
RUN_PID=$!

# Some vLLM HTTP clients retain worker threads after the Python CLI has
# checkpointed and printed its final summary.  Do not strand the allocation:
# once a fresh manifest proves the entire result is on disk, give the client a
# brief normal-exit grace period and then terminate only that client.  EXIT
# cleanup subsequently tears down the server process group.
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
