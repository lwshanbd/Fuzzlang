#!/bin/bash
# E7: does a much larger model already solve this task without fine-tuning?
#
# Every SFT result so far uses Gemma-3-4B, whose zero-shot repair rate is 16.7%
# on unseen files and 6.0% on unseen projects. Those are low starting points,
# and a low starting point flatters any improvement. If a 31B model repairs
# these errors zero-shot, the fine-tuning result says "we picked a weak base",
# not "the data teaches repair" -- so this has to be measured before any further
# training is planned.
#
# Same cohorts, same prompt, same window-rewrite parsing, same patched Clang as
# every other evaluation: only the model changes. The 31B is sharded across the
# node's GPUs by device_map=auto; no adapter is loaded.
set -uo pipefail

REPO=${REPO:-/p/lustre2/shan4/new-fuzzlang}
BIG=${BIG:-/p/lustre1/shan4/gemma/hf/hub/models--google--gemma-4-31B-it/snapshots/518276fb130dc81caf9a4f772e65e63ef2526493}
SMALL=${SMALL:-$REPO/.artifacts/models/gemma-3-4b-it}
COHORTS=${COHORTS:-$REPO/data/gen/experiments/e3-eval-cohorts-v0001}
OUT=${OUT:-$REPO/.artifacts/sft-eval/e7-bigbase}
MAX_INSTANCES=${MAX_INSTANCES:-150}
MAX_NEW_TOKENS=${MAX_NEW_TOKENS:-512}
PY=${PY:-/p/lustre1/shan4/gemma/venv/bin/python}

cd "$REPO"
mkdir -p "$OUT"
export HF_HOME=${HF_HOME:-/p/lustre1/shan4/gemma/hf}

evaluate() {  # label  model-path  cohort
    local out="$OUT/$1-seed42--$3.json"
    if [ -s "$out" ]; then echo "SKIP $1 / $3"; return; fi
    echo "=== eval $1 / $3 start $(date +%H:%M:%S)"
    PYTHONPATH=src "$PY" src/repair/run_adapter_eval.py \
        --base-model "$2" \
        --data-path "$COHORTS/$3.jsonl" \
        --clang-bin /p/lustre2/shan4/fuzzlang-clang/bin/clang++ \
        --clang-c-bin /p/lustre2/shan4/fuzzlang-clang/bin/clang \
        --diagtool-bin /p/lustre2/shan4/fuzzlang-clang/bin/diagtool \
        --out "$out" --max-instances "$MAX_INSTANCES" \
        --max-new-tokens "$MAX_NEW_TOKENS" --seed 42 \
        --target-format window-rewrite \
        --local-files-only 2>&1 | tail -5 || echo "FAIL $1 / $3"
}

for cohort in eval_unseen_tu heldout_project; do
    evaluate base31b "$BIG" "$cohort"
done
echo "=== E7 DONE $(date +%H:%M:%S)"
