# scripts/ — Fuzzlang v2 operational scripts

## Environment

- **`activate_dvcr.sh`** — sources the conda env + sets `LD_LIBRARY_PATH`, `PATH`, `PYTHONPATH`, and `FUZZLANG_{CLANG,DIAGTOOL}_BIN`. Source this at the top of every job.

## Build

- **`build_fuzzlang_clang.sh`** — clone stock llvm-project, apply Fuzzlang patch, build clang + diagtool at `-j${JOBS:-4}`. Run on the CPU-rich machine of your choice (or on Polaris login node with `-j4` and tmux, per the compile-discipline rule in `CLAUDE.md`). Produces `$PREFIX/bin/{clang,diagtool}`.
- **`patches/`** — one `.patch` file + README. See `patches/README.md` for what it does and why there is no Patch 2.

## Polaris PBS templates

- **`polaris_qsub_sft.sh`** — submits B2 LoRA SFT as a 1-node 4-GPU job. Outputs a LoRA adapter to `$ADAPTER_OUT`. Budget: ~8 node-hours for one run.
- **`polaris_qsub_sweep.sh`** — submits ONE (method, seed) cell of the main sweep. Launches a vLLM server bound to one A100, runs the DVCR harness against the eval split, writes `results/<stamp>.json`. Typical budget: ~2 node-hours per job.

Submission example for the full main-table row set:

```bash
for METHOD in b0_zero_shot b1_stderr_loop b2_static_sft dvcr dvcr_no_id dvcr_no_structure dvcr_no_loop; do
    for SEED in 17 23 42; do
        qsub -v "METHOD=$METHOD,SEED=$SEED" scripts/polaris_qsub_sweep.sh
    done
done
```

(21 jobs × ~2h = ~42 node-hours; fits in the 150 node-hour budget).

## Drivers (not yet implemented)

These scripts require a small amount of additional code that is not yet landed; stubbed here for reference:

- **`run_sft.py`** — LoRA SFT driver called by `polaris_qsub_sft.sh`. Will use `peft.LoraConfig` + `trl.SFTTrainer` against `(buggy, error, fixed)` triples. Matches the Fuzzlang v1 recipe for baseline equivalence.
- **`run_sweep.py`** — sweep driver called by `polaris_qsub_sweep.sh`. Loads the NatErr eval split, instantiates the right runner from `experiments.methods`, collects `InstanceResult` objects, writes a summary JSON with `summarize(results)` from `experiments.eval.metrics`.

These are TODOs for the next working session.
