#!/bin/bash
# Submit the NatErr snapshot campaign to Flux as N independent shards.
#
# Each shard walks its own slice of the snapshot plan round-robin, so every
# shard gets a mix of dense and sparse snapshots and they finish together.
# Shards never collide: each writes only its own `$OUT/<sha>/` directory, and
# each builds in node-local /tmp, which is both fast and self-cleaning.
#
# Node count is deliberately small.  The campaign is embarrassingly parallel
# and could take the whole queue; it does not, because concurrent node count is
# the scarce resource here, not core-hours.
set -uo pipefail

REPO=${REPO:-/p/lustre2/shan4/new-fuzzlang}
NSHARDS=${NSHARDS:-4}
MAX_SNAPSHOTS=${MAX_SNAPSHOTS:-41}
QUEUE=${QUEUE:-pllm}
WALL=${WALL:-720m}
CORES=${CORES:-64}
LOGDIR=${LOGDIR:-$REPO/.artifacts/naterr-campaign-logs}

mkdir -p "$LOGDIR"
cd "$REPO"

for ((shard = 0; shard < NSHARDS; shard++)); do
    flux batch --queue="$QUEUE" --nslots=1 --cores-per-slot="$CORES" \
        --job-name="naterr-$shard" -t "$WALL" \
        --output="$LOGDIR/shard-$shard.out" \
        --error="$LOGDIR/shard-$shard.err" \
        --setattr=system.shell.options.rlimit.nofile=8192 \
        --wrap bash -c "
            export SHARD=$shard NSHARDS=$NSHARDS MAX_SNAPSHOTS=$MAX_SNAPSHOTS
            export JOBS=$CORES SCRATCH=/tmp/\$USER/naterr-snap-$shard
            bash $REPO/src/real/run_naterr_snapshot_campaign.sh
        " || echo "FAILED to submit shard $shard"
done

echo "submitted $NSHARDS shards to $QUEUE; watch with: flux jobs"
echo "results accumulate under $REPO/data/natErr/snapshot-campaign/"
