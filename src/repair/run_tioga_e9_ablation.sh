#!/bin/bash
# E9: how much of the repair rate is the model, and how much is the hint?
#
# Every evaluation so far hands the model the diagnostic name, its message, and
# the exact file:line:col. That is a strong hint, and the obvious objection is
# that we are measuring "follow the compiler's instructions" rather than
# repair. This re-runs the *same* adapter on the *same* cohorts with the prompt
# progressively withholding that information:
#
#   full         name + message + location   (what the models were trained on)
#   no-location  name + message              (knows what, not where)
#   none         nothing                     (only "this does not compile")
#
# Nothing is retrained. The models saw `full` during training, so the drop
# measures reliance on the hint, not what they could learn without it -- worth
# stating plainly, because they are different questions.
set -uo pipefail
# The verifier compiles deliberately broken source, so Clang crashes are
# routine. Each crash dropped a core file into the working directory --
# 124 of them accumulated, all truncated to 16KB and useless for debugging.
ulimit -c 0

REPO=${REPO:-/p/lustre2/shan4/new-fuzzlang}
ADAPTER=${ADAPTER:-$REPO/.artifacts/sft-runs/e5-scaling/fuzzlang4000-seed42/adapter}
BASE=${BASE:-$REPO/.artifacts/models/gemma-3-4b-it}
LABEL=${LABEL:-fuzzlang4000}
COHORTS=${COHORTS:-$REPO/data/gen/experiments/e3-eval-cohorts-v0001}
OUT=${OUT:-$REPO/.artifacts/sft-eval/e9-ablation}
DETAILS=${DETAILS:-"no-location none"}
MAX_INSTANCES=${MAX_INSTANCES:-150}
PY=${PY:-/p/lustre1/shan4/gemma/venv/bin/python}

cd "$REPO"
mkdir -p "$OUT"

for detail in $DETAILS; do
    for cohort in eval_unseen_tu heldout_project; do
        out="$OUT/${LABEL}-${detail}-seed42--${cohort}.json"
        if [ -s "$out" ]; then echo "SKIP $detail / $cohort"; continue; fi
        echo "=== $LABEL detail=$detail cohort=$cohort start $(date +%H:%M:%S)"
        adapter_args=()
        [ -n "$ADAPTER" ] && adapter_args=(--adapter "$ADAPTER")
        PYTHONPATH=src "$PY" src/repair/run_adapter_eval.py \
            --base-model "$BASE" "${adapter_args[@]}" \
            --data-path "$COHORTS/${cohort}.jsonl" \
            --clang-bin /p/lustre2/shan4/fuzzlang-clang/bin/clang++ \
            --clang-c-bin /p/lustre2/shan4/fuzzlang-clang/bin/clang \
            --diagtool-bin /p/lustre2/shan4/fuzzlang-clang/bin/diagtool \
            --out "$out" --max-instances "$MAX_INSTANCES" \
            --max-new-tokens 512 --seed 42 \
            --target-format window-rewrite \
            --diagnostic-detail "$detail" \
            --local-files-only 2>&1 | tail -4 || echo "FAIL $detail / $cohort"
    done
done
echo "=== E9 DONE $(date +%H:%M:%S)"
