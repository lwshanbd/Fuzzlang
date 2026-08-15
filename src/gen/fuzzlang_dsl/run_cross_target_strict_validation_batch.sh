#!/usr/bin/env bash
# Replay 100+ target-routed generated Injectors inside one allocated CPU node.
# No Flux command is invoked here: caller owns the single-node allocation.
set -euo pipefail
ROOT=/p/lustre2/shan4/new-fuzzlang
EXPERIMENT="$ROOT/data/gen/experiments/clang-only-gemma-injectors-v0001/gemma-vllm-tp8-clang-test-adaptive-fragment-v0002"
ROUTES="$EXPERIMENT/cross-target-inputs-v0001"
POOLS="$ROOT/data/gen/source-pools/llvm-22.1.8-cross-target-noinclude-v0001"
OUT="$EXPERIMENT/cross-target-strict-validation-v0001"
CLANG_CXX=/p/lustre2/shan4/fuzzlang-clang/bin/clang++
CLANG_C=/p/lustre2/shan4/fuzzlang-clang/bin/clang
DIAGTOOL=/p/lustre2/shan4/fuzzlang-clang/bin/diagtool
cd "$ROOT"
export PYTHONPATH=src${PYTHONPATH:+:$PYTHONPATH}
mkdir -p "$OUT"
for label in x86_64_unknown arm64_linux x86_64_linux x86_64_unknown_linux i386_linux; do
  python3 src/gen/fuzzlang_dsl/run_campaign.py \
    --injectors "$ROUTES/$label.jsonl" --clean-sources "$POOLS/$label-sources.jsonl" \
    --clang-bin "$CLANG_CXX" --clang-c-bin "$CLANG_C" --diagtool-bin "$DIAGTOOL" \
    --records-out "$OUT/$label-records.jsonl" --rejections-out "$OUT/$label-rejections.jsonl" \
    --manifest-out "$OUT/$label-manifest.json" --timeout 20 \
    --max-sources-per-injector 1 --max-candidates-per-source 1 \
    --max-verifications-per-injector 1 --max-verifications 500 \
    --max-records-per-injector 1 --max-records-per-diagnostic 1 --max-records 500 \
    --checkpoint-every 25
done
