#!/usr/bin/env bash
# Strictly validate one large Injector batch inside one allocated CPU node.
#
# Submit exactly one Flux allocation with ``-N1 -n$FUZZLANG_STRICT_SHARDS``
# and ``-o exit-timeout=none``. Flux starts one rank per CPU worker inside that
# same node; every rank has isolated input/output files. The no-timeout setting
# is essential: shards have uneven compiler workloads, and the default
# post-first-exit timeout would otherwise kill slower ranks.
set -euo pipefail
# Candidate programs can expose compiler crashes; never leave core files in
# the shared repository while a large validation batch is running.
ulimit -c 0

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <output-directory>" >&2
  exit 2
fi

ROOT=/p/lustre2/shan4/new-fuzzlang
INPUT="${INPUT:-$ROOT/data/gen/experiments/clang-only-gemma-injectors-v0001/gemma-vllm-tp8-clang-test-v0001/injectors.jsonl}"
WITNESSES="${WITNESSES:-$ROOT/data/gen/experiments/clang-only-gemma-injectors-v0001/cpp23-witnesses.jsonl}"
SOURCES="${SOURCES:-$ROOT/data/gen/source-pools/llvm-22.1.8-cpp23-v0/sources.jsonl}"
CLANG_CXX="${CLANG_CXX:-/p/lustre2/shan4/fuzzlang-clang/bin/clang++}"
CLANG_C="${CLANG_C:-/p/lustre2/shan4/fuzzlang-clang/bin/clang}"
DIAGTOOL="${DIAGTOOL:-/p/lustre2/shan4/fuzzlang-clang/bin/diagtool}"
OUTPUT=$1
RANK=${FLUX_TASK_RANK:-0}
SHARDS=${FUZZLANG_STRICT_SHARDS:-16}

if (( RANK < 0 || RANK >= SHARDS )); then
  echo "rank $RANK is outside the configured $SHARDS validation shards" >&2
  exit 2
fi
for binary in "$CLANG_CXX" "$CLANG_C" "$DIAGTOOL"; do
  [[ -x "$binary" ]] || { echo "missing executable: $binary" >&2; exit 2; }
done

RANK_DIR="$OUTPUT/rank-$(printf '%02d' "$RANK")"
mkdir -p "$RANK_DIR"
ROUTED="$RANK_DIR/routed-sources.jsonl"

cd "$ROOT"
export PYTHONPATH=src${PYTHONPATH:+:$PYTHONPATH}

python3 src/gen/fuzzlang_dsl/build_witness_routed_source_pool.py \
  --injectors "$INPUT" \
  --witnesses "$WITNESSES" \
  --clean-sources "$SOURCES" \
  --shard-count "$SHARDS" \
  --shard-index "$RANK" \
  --out "$ROUTED"

python3 src/gen/fuzzlang_dsl/run_campaign.py \
  --injectors "$INPUT" \
  --shard-count "$SHARDS" \
  --shard-index "$RANK" \
  --clean-sources "$ROUTED" \
  --clang-bin "$CLANG_CXX" \
  --clang-c-bin "$CLANG_C" \
  --diagtool-bin "$DIAGTOOL" \
  --records-out "$RANK_DIR/records.jsonl" \
  --rejections-out "$RANK_DIR/rejections.jsonl" \
  --manifest-out "$RANK_DIR/manifest.json" \
  --timeout 20 \
  --max-sources-per-injector 10000 \
  --max-candidates-per-source 8 \
  --max-verifications-per-injector 50 \
  --max-verifications 4000 \
  --max-records-per-injector 10 \
  --max-records-per-diagnostic 1 \
  --max-records 1000 \
  --checkpoint-every 25
