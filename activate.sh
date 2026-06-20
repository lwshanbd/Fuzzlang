#!/usr/bin/env bash
# source this file to get a ready-to-use fuzzlang shell on Polaris.
#
#   source scripts/activate_fuzzlang.sh
#
# Sets up:
#   - miniforge3 on PATH
#   - `fuzzlang` conda env active (torch + transformers + vllm + peft + openai)
#   - /usr/lib64 on LD_LIBRARY_PATH so torch can find libcuda.so
#   - Fuzzlang-modified clang + diagtool on PATH
#   - PYTHONPATH = repo root

# Safe to source multiple times.
_fuzzlang_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
_fuzzlang_ENV=/lus/eagle/projects/diomp/baodi/envs/fuzzlang
_fuzzlang_CLANG_PREFIX=/lus/eagle/projects/diomp/baodi/softwares/fuzzlang-clang

if command -v module >/dev/null 2>&1; then
    module load miniforge3/24.3.0-0 2>/dev/null || true
fi

if [ -z "${CONDA_SHLVL:-}" ] || [ "${CONDA_PREFIX:-}" != "$_fuzzlang_ENV" ]; then
    # shellcheck source=/dev/null
    source /soft/spack/pe/0.10.1/base/install/linux-sles15-x86_64_v3/gcc-13.3.1/miniforge3-24.3.0-0-54otbc773he7wavfanq4eyis55yo4bbg/etc/profile.d/conda.sh
    conda activate "$_fuzzlang_ENV"
fi

export LD_LIBRARY_PATH="/usr/lib64:${LD_LIBRARY_PATH:-}"
export PATH="$_fuzzlang_CLANG_PREFIX/bin:$PATH"
export PYTHONPATH="$_fuzzlang_REPO_ROOT:${PYTHONPATH:-}"

export FUZZLANG_CLANG_BIN="$_fuzzlang_CLANG_PREFIX/bin/clang"
export FUZZLANG_DIAGTOOL_BIN="$_fuzzlang_CLANG_PREFIX/bin/diagtool"

echo "[fuzzlang] env: $(conda info --envs | grep -F \* | awk '{print $1}')"
echo "[fuzzlang] python: $(python --version 2>&1)"
echo "[fuzzlang] clang: $FUZZLANG_CLANG_BIN"
echo "[fuzzlang] repo: $_fuzzlang_REPO_ROOT"
