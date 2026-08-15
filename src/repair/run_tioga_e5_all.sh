#!/bin/bash
# E5 end to end on one allocation: train the nested FuzzLang tiers, then
# evaluate every tier plus the un-finetuned base on both held-out cohorts.
#
# Combined into a single job deliberately.  The queue reservation here is hours
# long, so splitting training and evaluation into two submissions would pay that
# wait twice for no benefit -- evaluation needs the same node and the same
# pinned stack.
set -uo pipefail

REPO=${REPO:-/p/lustre2/shan4/new-fuzzlang}
cd "$REPO"

echo "### E5 TRAINING START $(date)"
bash src/repair/run_tioga_e5_scaling.sh

echo "### E5 EVALUATION START $(date)"
# The eval driver is E3's: it walks $RUNS/*/adapter and names outputs
# <arm>-seed<N>--<cohort>.json, which is exactly what the scaling report parses.
# TARGET_FORMAT must stay window-rewrite -- the adapters were trained with it,
# and the offset representation silently scores near zero.
RUNS="$REPO/.artifacts/sft-runs/e5-scaling" \
OUT="$REPO/.artifacts/sft-eval/e5-scaling" \
TARGET_FORMAT=window-rewrite \
bash src/repair/run_tioga_e3_eval.sh

echo "### E5 REPORT $(date)"
PYTHONPATH=src python3 src/repair/run_scaling_report.py \
    --eval-dir "$REPO/.artifacts/sft-eval/e5-scaling" \
    --out-dir "$REPO/data/reports/e5-scaling-$(date +%Y%m%d)" || true

echo "### E5 DONE $(date)"
