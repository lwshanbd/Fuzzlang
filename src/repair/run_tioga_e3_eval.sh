#!/bin/bash
# E3 evaluation: every trained arm/seed plus the un-finetuned base, on both
# held-out cohorts, verified by the pinned patched Clang.
#
# Distinct C and C++ drivers are mandatory here: the unseen-project cohort is
# ~40% C, and compiling a .c file with clang++ produced a spurious failure in an
# earlier evaluation.
set -uo pipefail

REPO=${REPO:-/p/lustre2/shan4/new-fuzzlang}
RUNS=${RUNS:-$REPO/.artifacts/sft-runs/e3-v0002}
COHORTS=${COHORTS:-$REPO/data/gen/experiments/e3-eval-cohorts-v0001}
OUT=${OUT:-$REPO/.artifacts/sft-eval/e3-v0002}
BASE=${BASE:-$REPO/.artifacts/models/gemma-3-4b-it}
PY=${PY:-/p/lustre1/shan4/gemma/venv/bin/python}
MAX_INSTANCES=${MAX_INSTANCES:-150}
MAX_NEW_TOKENS=${MAX_NEW_TOKENS:-512}
# Must match how the adapters were trained; the eval CLI defaults to the
# offset representation, which the pilot already showed does not work.
TARGET_FORMAT=${TARGET_FORMAT:-window-rewrite}
SEED=${SEED:-42}

cd "$REPO"
mkdir -p "$OUT"

evaluate() {  # name  adapter-or-empty  cohort
    local name="$1" adapter="$2" cohort="$3"
    local out="$OUT/${name}--${cohort}.json"
    if [ -s "$out" ]; then echo "SKIP $name / $cohort"; return; fi
    local adapter_args=()
    [ -n "$adapter" ] && adapter_args=(--adapter "$adapter")
    echo "=== eval $name / $cohort"
    PYTHONPATH=src "$PY" src/repair/run_adapter_eval.py \
        --base-model "$BASE" "${adapter_args[@]}" \
        --data-path "$COHORTS/${cohort}.jsonl" \
        --clang-bin /p/lustre2/shan4/fuzzlang-clang/bin/clang++ \
        --clang-c-bin /p/lustre2/shan4/fuzzlang-clang/bin/clang \
        --diagtool-bin /p/lustre2/shan4/fuzzlang-clang/bin/diagtool \
        --out "$out" --max-instances "$MAX_INSTANCES" \
        --max-new-tokens "$MAX_NEW_TOKENS" --seed "$SEED" \
        --target-format "$TARGET_FORMAT" \
        --local-files-only 2>&1 | tail -6 || echo "FAIL $name / $cohort"
}

for cohort in eval_unseen_tu heldout_project; do
    evaluate base "" "$cohort"
    for run in "$RUNS"/*/; do
        [ -d "$run/adapter" ] || continue
        evaluate "$(basename "${run%/}")" "$run/adapter" "$cohort"
    done
done
echo "=== E3 EVAL DONE ==="
