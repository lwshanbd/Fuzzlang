#!/usr/bin/env bash
# Keep all validation workers inside one Flux task so early workers cannot
# trigger Flux's multi-task exit timeout and kill slower compiler workers.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <output-directory>" >&2
  exit 2
fi

ROOT=/p/lustre2/shan4/new-fuzzlang
OUTPUT=$1
WORKERS=${FUZZLANG_STRICT_WORKERS:-16}
RANK_SCRIPT="$ROOT/src/gen/fuzzlang_dsl/run_single_node_strict_feedback_validation.sh"

if (( WORKERS <= 0 )); then
  echo "FUZZLANG_STRICT_WORKERS must be positive" >&2
  exit 2
fi

pids=()
for ((rank = 0; rank < WORKERS; rank++)); do
  FLUX_TASK_RANK=$rank FUZZLANG_STRICT_SHARDS=$WORKERS \
    bash "$RANK_SCRIPT" "$OUTPUT" &
  pids+=("$!")
done

status=0
for pid in "${pids[@]}"; do
  wait "$pid" || status=1
done
exit "$status"
