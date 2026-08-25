#!/bin/bash
# Serve Gemma-4-31B with the FuzzLang LoRA attached, for E8 evaluation.
#
# A repo-owned variant of /p/lustre1/shan4/gemma/run/serve_entry.sh, which
# serves the base model only. Two changes and nothing else:
#   --enable-lora --lora-modules <name>=<path>, so the adapter can be selected
#   per request by model name, and the adapter directory mounted into the
#   container, since it lives on a filesystem the original never mounted.
#
# Serving rather than loading in-process is the point: vLLM shards with tensor
# parallelism, so every GPU works on every token. Loading a 31B with
# device_map="auto" instead gives one GPU's throughput for eight GPUs' worth of
# allocation -- how the first E7 run took 3h17m per cohort.
set -uo pipefail

GEMMA=${GEMMA:-/p/lustre1/shan4/gemma}
IMG_TAR=${IMG_TAR:-$GEMMA/podman/vllm-gemma4.tar}
IMG=${IMG:-localhost/vllm-gemma4:rocm723}
ADAPTER=${ADAPTER:?ADAPTER (host path to the LoRA directory) is required}
LORA_NAME=${LORA_NAME:-gemma-4-31B-it-fuzzlang}
PORT=${PORT:-8000}
TP=${TP:-8}
EAGER=${EAGER:-1}

export TMPDIR=/tmp/$USER; mkdir -p "$TMPDIR/pstore" "$TMPDIR/prun"
P=(podman --root "$TMPDIR/pstore" --runroot "$TMPDIR/prun" --storage-driver overlay)

echo "[serve-lora] host=$(hostname) port=$PORT tp=$TP adapter=$ADAPTER"
"${P[@]}" load -i "$IMG_TAR" >/dev/null
DEVS=(--device /dev/kfd); for d in /dev/dri/renderD*; do DEVS+=(--device "$d"); done

"${P[@]}" run --rm "${DEVS[@]}" \
  --group-add keep-groups --ipc=host --security-opt seccomp=unconfined \
  --network host \
  -v "$GEMMA/hf":/hf \
  -v "$ADAPTER":/adapter:ro \
  -e HF_HOME=/hf -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
  -e XDG_CACHE_HOME=/tmp/.cache -e TRITON_CACHE_DIR=/tmp/.triton \
  "$IMG" bash -lc "
    ARGS=(google/gemma-4-31B-it
      --served-model-name gemma-4-31B-it
      --tensor-parallel-size $TP --dtype bfloat16
      --max-model-len 8192 --gpu-memory-utilization 0.90
      --limit-mm-per-prompt '{\"image\":0,\"audio\":0}'
      --enable-lora --max-lora-rank 64
      --lora-modules $LORA_NAME=/adapter
      --host 0.0.0.0 --port $PORT)
    [ '$EAGER' = '1' ] && ARGS+=(--enforce-eager)
    exec vllm serve \"\${ARGS[@]}\"
  "
