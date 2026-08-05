#!/usr/bin/env bash
# Synthesize direct lexical FuzzLang Injectors with local Gemma, then replay
# them only on their independently clean-gated real-source witnesses.  This
# runs entirely inside one existing Flux allocation: it never submits a nested
# job and never turns a Clang regression test into a dataset source.
set -euo pipefail
ulimit -c 0

: "${REQUESTS:?set REQUESTS to direct Injector synthesis JSONL}"
: "${WITNESSES:?set WITNESSES to the matching CodeWitness request JSONL}"
: "${CLEAN_SOURCES:?set CLEAN_SOURCES to the canonical clean-source JSONL}"
: "${OUTPUT_DIR:?set OUTPUT_DIR to the campaign directory}"

ROOT=/p/lustre2/shan4/new-fuzzlang
CLANG_CXX="${CLANG_CXX:-/p/lustre2/shan4/fuzzlang-clang/bin/clang++}"
CLANG_C="${CLANG_C:-/p/lustre2/shan4/fuzzlang-clang/bin/clang}"
DIAGTOOL="${DIAGTOOL:-/p/lustre2/shan4/fuzzlang-clang/bin/diagtool}"
SYNTHESIS_DIR="$OUTPUT_DIR/direct-gemma"
REPLAY_DIR="$OUTPUT_DIR/direct-replay"
ROUTED_SOURCES="$REPLAY_DIR/routed-sources.jsonl"

for binary in "$CLANG_CXX" "$CLANG_C" "$DIAGTOOL"; do
    [[ -x "$binary" ]] || { echo "missing executable: $binary" >&2; exit 2; }
done

mkdir -p "$SYNTHESIS_DIR" "$REPLAY_DIR"
cd "$ROOT"
export PYTHONPATH=src${PYTHONPATH:+:$PYTHONPATH}

# This launcher starts Gemma-4-31B locally and tears it down before compiler
# replay.  The model is asked for an Injector, not a direct broken sample.
REQUESTS="$REQUESTS" OUTPUT_DIR="$SYNTHESIS_DIR" \
    REQUEST_BATCH_SIZE="${REQUEST_BATCH_SIZE:-16}" \
    VLLM_CONCURRENCY="${VLLM_CONCURRENCY:-16}" \
    CANDIDATES="${CANDIDATES:-4}" \
    FEEDBACK_ROUNDS="${FEEDBACK_ROUNDS:-2}" \
    MAX_TOKENS="${MAX_TOKENS:-900}" \
    SYNTHESIS_MODE=lexical EAGER="${EAGER:-1}" \
    bash src/gen/fuzzlang_dsl/run_tioga_vllm_synthesis.sh

python3 src/gen/fuzzlang_dsl/build_witness_routed_source_pool.py \
    --injectors "$SYNTHESIS_DIR/injectors.jsonl" \
    --witnesses "$WITNESSES" \
    --clean-sources "$CLEAN_SOURCES" \
    --out "$ROUTED_SOURCES"

# Exact typed diagnostic equality, clean-parent compilation, and paired
# corrected source are all enforced by run_campaign.  A result is not
# coverage merely because Gemma returned a schema-valid Injector.
python3 src/gen/fuzzlang_dsl/run_campaign.py \
    --injectors "$SYNTHESIS_DIR/injectors.jsonl" \
    --clean-sources "$ROUTED_SOURCES" \
    --clang-bin "$CLANG_CXX" --clang-c-bin "$CLANG_C" \
    --diagtool-bin "$DIAGTOOL" \
    --records-out "$REPLAY_DIR/records.jsonl" \
    --rejections-out "$REPLAY_DIR/rejections.jsonl" \
    --manifest-out "$REPLAY_DIR/manifest.json" \
    --timeout 20 --max-sources-per-injector 3 \
    --max-candidates-per-source 8 --max-verifications-per-injector 24 \
    --max-verifications 400 --max-records-per-injector 3 \
    --max-records-per-diagnostic 1 --max-records 32 --checkpoint-every 10
