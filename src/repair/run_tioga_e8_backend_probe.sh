#!/bin/bash
# Is a low parse rate the model, or the way the serving path applies the LoRA?
#
# The 31B adapter scored 0.76 parse when served by vLLM, against 1.00 for the
# fine-tuned 4B. Its exact-match rate (0.640 against 0.033 zero-shot) proves the
# adapter is doing *something*, and the outputs that do parse fix 90% -- so the
# model learned the task and roughly a quarter of its answers come back without
# the JSON wrapper.
#
# One suspect: the adapter names its target modules with a regex, and vLLM
# matches LoRA modules by name. If it recognises only some of them the model is
# partially adapted, which would look exactly like this. Loading the same
# adapter locally through peft answers the question: same parse rate means the
# model, a much higher one means the serving path.
#
# It also fixes a comparison error. E7 measured the 31B zero-shot through the
# local path; E8 measured it fine-tuned through vLLM. Comparing those two is
# comparing inference paths as much as models, so the fine-tuned model has to be
# re-measured the way the baseline was. That costs ~3.5h per cohort, which is
# what a valid comparison costs here.
set -uo pipefail

REPO=${REPO:-/p/lustre2/shan4/new-fuzzlang}
BIG=${BIG:-/p/lustre1/shan4/gemma/hf/hub/models--google--gemma-4-31B-it/snapshots/518276fb130dc81caf9a4f772e65e63ef2526493}
ADAPTER=${ADAPTER:-$REPO/.artifacts/sft-runs/e8-big/fuzzlang4000-31b-seed42/adapter}
COHORT=${COHORT:-eval_unseen_tu}
N=${N:-150}
OUT=${OUT:-$REPO/.artifacts/sft-eval/e8-probe}
PY=${PY:-/p/lustre1/shan4/gemma/venv/bin/python}

cd "$REPO"
mkdir -p "$OUT"
export HF_HOME=${HF_HOME:-/p/lustre1/shan4/gemma/hf}

echo "=== local peft probe: $N instances of $COHORT, start $(date +%H:%M:%S)"
PYTHONPATH=src "$PY" src/repair/run_adapter_eval.py \
    --base-model "$BIG" --adapter "$ADAPTER" \
    --data-path "$REPO/data/gen/experiments/e3-eval-cohorts-v0001/${COHORT}.jsonl" \
    --clang-bin /p/lustre2/shan4/fuzzlang-clang/bin/clang++ \
    --clang-c-bin /p/lustre2/shan4/fuzzlang-clang/bin/clang \
    --diagtool-bin /p/lustre2/shan4/fuzzlang-clang/bin/diagtool \
    --out "$OUT/local${N}--${COHORT}.json" \
    --max-instances "$N" --max-new-tokens 512 --seed 42 \
    --target-format window-rewrite --local-files-only 2>&1 | tail -4
echo "=== probe done $(date +%H:%M:%S)"
