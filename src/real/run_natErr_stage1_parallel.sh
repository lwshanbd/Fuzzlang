#!/usr/bin/env bash
# Submit NatErr Stage 1 across multiple SLURM nodes in parallel.
#
# Each node clones a disjoint subset of the 8 default projects, harvests
# fix-build commits, and writes its own manifest. After all nodes finish,
# `cat $SCRATCH/natErr/manifest_node_*.jsonl > combined.jsonl` to merge.
#
# Why -c 64 (full-node reservation per srun) instead of -c 4: with -c 4,
# slurm packs all 4 sruns onto one 64-core node and they contend on the
# same NIC for git-clone bandwidth. Asking for the whole node forces slurm
# to spread to 4 distinct nodes — chromium alone saturates a NIC.
#
# Usage (from repo root):
#   bash scripts/run_natErr_stage1_parallel.sh
#
# Env overrides:
#   REPO     — path to repo (default: $PWD)
#   SCRATCH  — scratch root (default: /shared/scratch1/Users/$USER/Fuzzlang)
#   WALLTIME — per-node walltime (default: 04:00:00)
#   ACCOUNT  — slurm account (default: app)
#   PARTITION — slurm partition (default: pine)
#
# Sub-bucketing of projects is biased by expected shallow-clone size so the
# longest pole (chromium) runs alone:
#   node 1: chromium                              (~10-20 GB, ~1-2 h on Google's link)
#   node 2: libreoffice + ffmpeg + bitcoin        (~6 GB, ~10 min)
#   node 3: llvm + qt                             (~4.5 GB, ~15 min)
#   node 4: blender + postgresql                  (~3.5 GB, ~3 min)

set -euo pipefail

REPO="${REPO:-$PWD}"
SCRATCH="${SCRATCH:-/shared/scratch1/Users/$USER/Fuzzlang}"
WALLTIME="${WALLTIME:-04:00:00}"
ACCOUNT="${ACCOUNT:-app}"
PARTITION="${PARTITION:-pine}"

LOGDIR="$REPO/logs/stage1"
mkdir -p "$LOGDIR" "$SCRATCH/natErr"

run_node() {
    local NID=$1 PROJECTS=$2
    srun -p "$PARTITION" --account="$ACCOUNT" -N 1 -c 64 -t "$WALLTIME" \
        -J "fl-stage1-$NID" \
        --output="$LOGDIR/node_${NID}.log" \
        bash -lc "
            set -euo pipefail
            cd $REPO
            module load anaconda3/2024.02
            source .venv/bin/activate
            mkdir -p $SCRATCH/natErr/cks_${NID}
            echo \"[node-${NID}] hostname: \$(hostname)  start: \$(date)\"
            echo \"[node-${NID}] projects: ${PROJECTS}\"
            PYTHONPATH=. python scripts/run_natErr_stage1.py \\
                --only ${PROJECTS} \\
                --shallow \\
                --checkout-root $SCRATCH/natErr/cks_${NID} \\
                --manifest-out  $SCRATCH/natErr/manifest_node_${NID}.jsonl
            echo \"[node-${NID}] end: \$(date)\"
            du -sh $SCRATCH/natErr/cks_${NID}/* 2>/dev/null || true
        " &
}

run_node 1 chromium
run_node 2 libreoffice,ffmpeg,bitcoin
run_node 3 llvm,qt
run_node 4 blender,postgresql
wait

echo "[stage1-parallel] all nodes done at $(date)"
echo "[stage1-parallel] per-node manifests:"
wc -l "$SCRATCH/natErr/manifest_node_"*.jsonl
echo "[stage1-parallel] to merge:"
echo "  cat $SCRATCH/natErr/manifest_node_*.jsonl > $REPO/data/natErr/manifest_full.jsonl"
