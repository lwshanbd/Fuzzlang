#!/usr/bin/env bash
# Clone stock llvm-project, apply Fuzzlang patches, build Clang + diagtool.
#
# Run this on a CPU-rich machine (not the Polaris login node, per the repo's
# compile-discipline note in README_PORTABILITY.md). A full build takes
# ~1-2 hours at -j32 on a modern workstation.
#
# Produces:
#   $PREFIX/bin/clang      - Fuzzlang-modified Clang (emits DiagID: N on stderr)
#   $PREFIX/bin/diagtool   - Fuzzlang-modified diagtool (with find-diagnostic-name)
#
# Override any of: LLVM_VERSION, JOBS, PREFIX, BUILD_DIR.

set -euo pipefail

LLVM_VERSION="${LLVM_VERSION:-llvmorg-19.1.7}"
JOBS="${JOBS:-4}"                        # default safe for shared login nodes; bump to 16-32 off-Polaris
PREFIX="${PREFIX:-$HOME/fuzzlang-clang}"
BUILD_DIR="${BUILD_DIR:-$(pwd)/llvm-build}"
SRC_DIR="${SRC_DIR:-$(pwd)/llvm-project}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCH_DIR="$SCRIPT_DIR/patches"

echo "[build_fuzzlang_clang] version=$LLVM_VERSION  jobs=$JOBS  prefix=$PREFIX"
echo "[build_fuzzlang_clang] src=$SRC_DIR  build=$BUILD_DIR"
echo "[build_fuzzlang_clang] patch dir=$PATCH_DIR"

if [ ! -d "$SRC_DIR" ]; then
    echo "[build_fuzzlang_clang] cloning llvm-project @ $LLVM_VERSION"
    git clone --depth 1 --branch "$LLVM_VERSION" \
        https://github.com/llvm/llvm-project.git "$SRC_DIR"
fi

echo "[build_fuzzlang_clang] applying Fuzzlang patch"
(
    cd "$SRC_DIR"
    for p in "$PATCH_DIR"/0001-*.patch; do
        echo "  - applying $(basename "$p")"
        # Idempotent apply: skip if already applied.
        if git apply --reverse --check "$p" 2>/dev/null; then
            echo "    already applied, skipping"
            continue
        fi
        if git apply --check "$p" 2>/dev/null; then
            git apply "$p"
        else
            echo "    git apply rejected; falling back to patch -p1 --fuzz=3"
            patch -p1 --fuzz=3 < "$p" || {
                echo "    ERROR: patch $p did not apply cleanly."
                echo "    See src/foundation/patches/README.md for manual derivation notes."
                exit 1
            }
        fi
    done
)

echo "[build_fuzzlang_clang] configuring"
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"
cmake -G Ninja "$SRC_DIR/llvm" \
    -DCMAKE_BUILD_TYPE=Release \
    -DLLVM_ENABLE_PROJECTS="clang" \
    -DLLVM_TARGETS_TO_BUILD="X86" \
    -DLLVM_ENABLE_ASSERTIONS=OFF \
    -DCMAKE_INSTALL_PREFIX="$PREFIX" \
    -DLLVM_PARALLEL_COMPILE_JOBS="$JOBS" \
    -DLLVM_PARALLEL_LINK_JOBS=2

echo "[build_fuzzlang_clang] building clang + diagtool with -j$JOBS"
ninja -j"$JOBS" clang diagtool

echo "[build_fuzzlang_clang] installing to $PREFIX"
cmake --install . --component clang
# clang-resource-headers ships clang's own builtin headers (stddef.h,
# stdint.h, etc.). Without them the installed clang fails on any non-trivial
# C/C++ source with `fatal error: 'stddef.h' file not found`. The clang
# component does not include them, so install them explicitly.
cmake --install . --component clang-resource-headers || {
    echo "[build_fuzzlang_clang] clang-resource-headers install via cmake failed"
    echo "  (likely cmake_install.cmake has stale absolute paths from a moved"
    echo "  build tree). Falling back to manual copy from build dir."
    HEADERS_SRC="$BUILD_DIR/lib/clang"
    HEADERS_DST="$PREFIX/lib/clang"
    if [ -d "$HEADERS_SRC" ]; then
        mkdir -p "$HEADERS_DST"
        cp -r "$HEADERS_SRC"/. "$HEADERS_DST"/
        echo "  copied $HEADERS_SRC -> $HEADERS_DST"
    else
        echo "  ERROR: $HEADERS_SRC missing too. Clang will be broken."
        exit 1
    fi
}
# diagtool is not part of clang's install component in upstream LLVM — just
# copy the built binary into $PREFIX/bin alongside clang.
mkdir -p "$PREFIX/bin"
cp -f "$BUILD_DIR/bin/diagtool" "$PREFIX/bin/diagtool"

echo "[build_fuzzlang_clang] smoke test: patched clang should emit DiagID"
cat > /tmp/fuzzlang_smoke.c <<'EOF'
int main() { int x = 1 }
EOF
# clang exits non-zero on the syntax error and `grep -q` closes the pipe
# early, so under `set -euo pipefail` a direct `clang | grep -q` pipeline
# falsely reports failure even when DiagID is present. Capture stderr to a
# variable first (with `|| true`) and grep that.
SMOKE_OUT=$("$PREFIX/bin/clang" -c /tmp/fuzzlang_smoke.c 2>&1 || true)
if echo "$SMOKE_OUT" | grep -q '^DiagID:'; then
    echo "  OK: patched clang emits DiagID"
else
    echo "  FAIL: patched clang did NOT emit DiagID. Inspect Patch 1."
    echo "  --- clang stderr ---"
    echo "$SMOKE_OUT"
    exit 1
fi

DIAG_ID=$(echo "$SMOKE_OUT" | grep -oE 'DiagID: [0-9]+' | head -1 | awk '{print $2}')
DIAG_LOOKUP=$("$PREFIX/bin/diagtool" find-diagnostic-id "$DIAG_ID" 2>&1 || true)
if echo "$DIAG_LOOKUP" | grep -q '^err_'; then
    echo "  OK: diagtool find-diagnostic-id $DIAG_ID resolves to an err_* name"
else
    echo "  FAIL: stock diagtool reverse-lookup did not return a name for $DIAG_ID."
    echo "       (If this is LLVM < 17, the stock fallback may not exist; restore Patch 2.)"
    echo "  --- diagtool output ---"
    echo "$DIAG_LOOKUP"
    exit 1
fi

# Verify clang's resource headers are reachable. Compiling something that
# pulls <stddef.h> indirectly catches the "missing clang-resource-headers"
# install bug that bit us once.
cat > /tmp/fuzzlang_resource_smoke.c <<'EOF'
#include <stddef.h>
size_t whatever(void) { return sizeof(int); }
EOF
RES_OUT=$("$PREFIX/bin/clang" -c -o /dev/null /tmp/fuzzlang_resource_smoke.c 2>&1 || true)
if [ -z "$RES_OUT" ]; then
    echo "  OK: patched clang resolves <stddef.h> (resource headers installed)"
else
    echo "  FAIL: patched clang cannot find its own resource headers."
    echo "  --- clang stderr ---"
    echo "$RES_OUT"
    exit 1
fi
rm -f /tmp/fuzzlang_resource_smoke.c

rm -f /tmp/fuzzlang_smoke.c /tmp/fuzzlang_smoke.o
echo "[build_fuzzlang_clang] DONE. clang: $PREFIX/bin/clang"
