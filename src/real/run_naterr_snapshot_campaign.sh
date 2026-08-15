#!/bin/bash
# NatErr snapshot campaign.
#
# A candidate can only be reproduced against a compile environment close to its
# own commit: a 2023 file does not compile against a 2026 header tree, and the
# TableGen-generated `.inc` files cannot be recovered by checking out sources
# alone.  So each snapshot materialises the LLVM tree at one commit, configures
# it, and builds *only* the TableGen targets -- minutes, not the hour a full
# clang build costs -- then reproduces and pairs every candidate in its window.
#
# Snapshots run densest-cluster-first, so stopping the campaign early still
# leaves the most valuable builds done.  Each snapshot's tree and build
# directory are deleted as soon as its candidates are paired: they live on
# tmpfs, where `git archive` runs 45x faster than on the parallel filesystem,
# and only one is on disk at a time.
set -uo pipefail

REPO=${REPO:-/p/lustre2/shan4/new-fuzzlang}
LLVM_GIT=${LLVM_GIT:-$REPO/external/llvm-project}
MANIFEST=${MANIFEST:-$REPO/data/natErr/manifest_llvm_selfcontained.jsonl}
PLAN=${PLAN:-$REPO/data/natErr/snapshot-plan.json}
OUT=${OUT:-$REPO/data/natErr/snapshot-campaign}
SCRATCH=${SCRATCH:-/tmp/$USER/naterr-snap}
CLANG=${CLANG:-/p/lustre2/shan4/fuzzlang-clang/bin/clang}
DIAGTOOL=${DIAGTOOL:-/p/lustre2/shan4/fuzzlang-clang/bin/diagtool}
WINDOW=${WINDOW:-21}
JOBS=${JOBS:-48}
MAX_SNAPSHOTS=${MAX_SNAPSHOTS:-8}
# Only 25% of candidates touch a file a clang+X86 build compiles; mlir and the
# extra targets roughly double that. lldb/flang would add more again but pull
# in swig/Fortran toolchains, so they stay out.
PROJECTS=${PROJECTS:-"clang;mlir"}
TARGETS=${TARGETS:-"X86;AArch64;RISCV;AMDGPU;NVPTX"}

cd "$REPO"
mkdir -p "$OUT" "$SCRATCH"
export PYTHONPATH=src

if [ ! -s "$PLAN" ]; then
    python3 src/real/run_naterr_plan.py --manifest "$MANIFEST" \
        --window-days "$WINDOW" --plan-out "$PLAN" >/dev/null || exit 1
fi

# SHARD/NSHARDS splits the plan round-robin across nodes.  Round-robin rather
# than contiguous blocks so every shard gets a mix of dense and sparse
# snapshots and they finish at roughly the same time.
SHARD=${SHARD:-0}
NSHARDS=${NSHARDS:-1}

mapfile -t ENTRIES < <(python3 -c "
import json
plan=json.load(open('$PLAN'))['snapshots'][:$MAX_SNAPSHOTS]
for i, s in enumerate(plan):
    if i % $NSHARDS == $SHARD:
        print(s['fix_sha'], s['date'], s['covers'])
")
echo "shard $SHARD/$NSHARDS: ${#ENTRIES[@]} snapshots"

for entry in "${ENTRIES[@]}"; do
    read -r SHA DATE COVERS <<< "$entry"
    SHORT=${SHA:0:12}
    if [ -s "$OUT/$SHORT/manifest.json" ]; then
        echo "SKIP $SHORT ($DATE) - already paired"; continue
    fi
    SRC=$SCRATCH/$SHORT/src
    BUILD=$SCRATCH/$SHORT/build
    echo "=== snapshot $SHORT  $DATE  covers=$COVERS"

    rm -rf "$SCRATCH/$SHORT"; mkdir -p "$SRC" "$BUILD" "$OUT/$SHORT"

    # 1. the source tree as it stood at this commit.  Every subproject named in
    # PROJECTS has to be materialised too, or cmake fails at configure time.
    if ! (cd "$LLVM_GIT" && git archive "$SHA" llvm clang mlir cmake third-party) \
            | tar -x -C "$SRC"; then
        echo "FAIL archive $SHORT"; rm -rf "$SCRATCH/$SHORT"; continue
    fi
    # Stage 2 reads historical file versions with `git show` from --llvm-src and
    # also maps compile-DB paths against it, so the materialised tree has to be
    # both.  A .git file pointing at the real object store makes it both.
    echo "gitdir: $(cd "$LLVM_GIT" && git rev-parse --absolute-git-dir)" > "$SRC/.git"

    # 2. configure, then build only what generates headers
    if ! (cd "$BUILD" && cmake -G "Unix Makefiles" "$SRC/llvm" \
            -DCMAKE_BUILD_TYPE=Release -DLLVM_ENABLE_PROJECTS="$PROJECTS" \
            -DLLVM_TARGETS_TO_BUILD="$TARGETS" -DLLVM_ENABLE_ASSERTIONS=OFF \
            -DCMAKE_EXPORT_COMPILE_COMMANDS=ON -DLLVM_INCLUDE_TESTS=OFF \
            -DLLVM_INCLUDE_BENCHMARKS=OFF) > "$OUT/$SHORT/cmake.log" 2>&1; then
        echo "FAIL cmake $SHORT (see $OUT/$SHORT/cmake.log)"
        rm -rf "$SCRATCH/$SHORT"; continue
    fi
    # One target at a time: the set of TableGen umbrella targets differs across
    # four years of LLVM, and `make` fails outright on an unknown target -- which
    # would leave a snapshot with no generated headers at all rather than with
    # most of them.
    # Per-target TableGen is separate from the umbrella targets and is not
    # optional: without it every `llvm/lib/Target/**` translation unit fails on
    # a missing `<Target>Gen*.inc`, which is where a large share of candidates
    # live. The target names are discovered rather than hardcoded, because the
    # enabled set follows TARGETS and the naming has changed over the years.
    TARGET_TG=$(cd "$BUILD" && make help 2>/dev/null \
        | grep -oE "[A-Za-z0-9_]+CommonTableGen" | sort -u | tr '\n' ' ')
    BUILT=0
    for target in intrinsics_gen clang-tablegen-targets omp_gen mlir-headers $TARGET_TG; do
        if (cd "$BUILD" && make -j"$JOBS" "$target") \
                >> "$OUT/$SHORT/make.log" 2>&1; then
            BUILT=$((BUILT + 1))
        else
            echo "  note: target $target unavailable at this revision"
        fi
    done
    if [ "$BUILT" -eq 0 ]; then
        echo "FAIL no tablegen target built for $SHORT"
        rm -rf "$SCRATCH/$SHORT"; continue
    fi

    # 3. the candidates this build can serve
    python3 src/real/run_naterr_plan.py --manifest "$MANIFEST" \
        --window-days "$WINDOW" --snapshot-date "$DATE" \
        --out "$OUT/$SHORT/window.jsonl" || continue

    # 4. reproduce, then pair and revalidate
    python3 src/real/reproduce_stage2_llvm.py \
        --manifest "$OUT/$SHORT/window.jsonl" \
        --llvm-src "$SRC" --build-dir "$BUILD" \
        --clang-bin "$CLANG" --diagtool-bin "$DIAGTOOL" \
        --out "$OUT/$SHORT/reproduced.jsonl" \
        --summary-out "$OUT/$SHORT/reproduced.summary.json" \
        --skip-build --jobs "$JOBS" > "$OUT/$SHORT/stage2.log" 2>&1

    if [ -s "$OUT/$SHORT/reproduced.jsonl" ]; then
        python3 src/real/run_formalize_naterr.py \
            --input "$OUT/$SHORT/reproduced.jsonl" \
            --project llvm --project-checkout "$SRC" \
            --clang-bin "$CLANG" --diagtool-bin "$DIAGTOOL" \
            --out "$OUT/$SHORT/records.jsonl" \
            --rejected-out "$OUT/$SHORT/rejected.jsonl" \
            --manifest-out "$OUT/$SHORT/manifest.json" \
            --jobs "$JOBS" --timeout 180 > "$OUT/$SHORT/formalize.log" 2>&1
        echo "  accepted $(wc -l < "$OUT/$SHORT/records.jsonl" 2>/dev/null || echo 0)"
    else
        echo "  no candidate reproduced"
        echo '{"counts":{"accepted":0,"input_rows":0}}' > "$OUT/$SHORT/manifest.json"
    fi

    rm -rf "$SCRATCH/$SHORT"
done

echo "=== CAMPAIGN DONE ==="
cat "$OUT"/*/records.jsonl 2>/dev/null | wc -l | xargs echo "total accepted records:"
