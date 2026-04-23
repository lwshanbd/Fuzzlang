# Literature Scan (for Fuzzlang NeurIPS 2026 re-submission)

> Scope: 2023-2026 work in four buckets, used to ground the method thesis and avoid the OOPSLA rejection's "weak novelty / weak related work" complaints. Items flagged `NEEDS-VERIFY` must be checked against arXiv/Scholar before citation.

## Bucket 1: LLM-based compiler / fuzzer work (the novelty baseline)

- **Fuzz4All** (ICSE 2024, arXiv:2308.04748) — universal LLM fuzzer across GCC/Clang/Z3/Go/Java. Autoprompting + LLM input generation. *Coverage-guided only, no diagnostic-ID feedback.*
- **TitanFuzz** (ISSTA 2023, arXiv:2212.14834) — LLM-generated DL API calls. Origin of "LLM-as-fuzzer".
- **WhiteFox** (OOPSLA 2024, arXiv:2310.15991) — white-box DL-compiler fuzzer, two LLMs (analyzer + generator). *Targets miscompilations, not diagnostic coverage.*
- **FuzzGPT** (ICSE 2024, arXiv:2304.02014) — primes LLM with historical bug-triggering programs.
- **LLAMAFuzz** (arXiv:2406.07714, 2024) — LLM-augmented greybox fuzzer.
- **"LLM-Based Fuzzing Techniques: A Survey"** (arXiv:2402.00350, 2024) — useful framing for related work.

**Wedge**: none of these use the compiler's **structured diagnostic ID** as a supervision or verification signal. They treat the compiler output as coverage or as miscompilation witness, never as a 488-class label space.

## Bucket 2: Code repair with compiler/executor feedback (the method baselines)

- **Self-Debugging** (Chen et al., ICLR 2024, arXiv:2304.05128) — LLM explains own output + uses execution feedback. Text-level.
- **Reflexion** (NeurIPS 2023, arXiv:2303.11366) — verbal self-reflection on execution traces.
- **SWE-agent** (NeurIPS 2024, arXiv:2405.15793) — agent-computer interface for repo-level bugs. Uses tests, not compiler diagnostics.
- **Agentless** (arXiv:2407.01489, 2024) — no-agent pipeline, strong baseline; shows simple iteration beats agentic scaffolding.
- **AutoCodeRover** (ISSTA 2024, arXiv:2404.05427) — AST-aware repo navigation + test feedback.
- **CodeAct** (ICML 2024, arXiv:2402.01030) — executable code as action space for agents.
- **RLEF** (Meta, arXiv:2410.02089, 2024) — **RL from execution feedback** on competitive programming. Closest prior to "compiler as reward"; uses pass/fail, not diagnostic ID.
- **LDB** (arXiv:2402.16906, 2024) — runtime-state-guided debugging.
- **OpenCodeInterpreter** (ACL Findings 2024, arXiv:2402.14658) — execution-feedback SFT dataset.
- **Inference-time compute verifier-grounded search**:
  - **AlphaCodium** (arXiv:2401.08500, 2024)
  - **Large Language Monkeys / Brown et al.** (arXiv:2407.21787, 2024) — best-of-N with verifier
  - **Archon** (arXiv:2409.15254, 2024)
- **Coffee-Gym** (arXiv:2409.19715, 2024 — `NEEDS-VERIFY`) — RL env for code repair with compiler.
- **CYCLE** (OOPSLA 2024 — `NEEDS-VERIFY` exact title) — iterative refinement with test feedback.

**Wedge**: every feedback-loop method either (a) treats compiler output as unstructured stderr text or (b) collapses it to pass/fail. Nobody uses the 488-class structured diagnostic ID as a dense, typed verifier signal.

## Bucket 3: Data contamination / rigor (answers rejection reason #3)

- **LiveCodeBench** (Jain et al., NeurIPS 2024 D&B, arXiv:2403.07974) — temporal-cutoff contamination control. *Adopt temporal-holdout protocol for LLVM commits.*
- **EvalPlus / HumanEval+ / MBPP+** (NeurIPS 2023 D&B, arXiv:2305.01210) — stress-tested tests.
- **Riddell et al., "Quantifying Contamination in Code Generation"** (ICSE 2024, arXiv:2403.04811) — direct methodology for train/test leakage in code LLMs. *Directly addresses reviewer's complaint.*
- **Golchin & Surdeanu, "Time Travel in LLMs"** (ICLR 2024, arXiv:2308.08493) — contamination detection.
- **BigCodeBench** (ICLR 2025, arXiv:2406.15877) — contamination-aware benchmark.
- **CRUXEval** (ICML 2024, arXiv:2401.03065) — execution-reasoning benchmark.
- **SWE-bench Verified** (2024) — curated against contamination.

**Action for Fuzzlang**: project-level + temporal holdout + AST-hash dedup + diagnostic-family stratified split, reported side-by-side with the old 80/20 number so the delta is explicit.

## Bucket 4: HPC / directive-based + LLMs (the user's domain advantage)

- **Shan, Araya-Polo, Chapman, "Evaluation of Directive-Based Programming Models for Stencil Computation on Current GPGPU Architectures"** (Advancing OpenMP for Future Accelerators, 2024) — user's own prior work. Grounds HPC framing.
- **HPC-Coder / HPC-Coder-v2** (Nichols et al., SC 2024, arXiv:2306.17281 + follow-up) — LLM fine-tuned on HPC / OpenMP pragmas.
- **OMPGPT** (ISC 2024, arXiv:2401.16445) — domain LM for OpenMP pragmas.
- **ParEval** (Nichols et al., SC 2024, arXiv:2401.16395) — parallel code generation benchmark (OpenMP/MPI/CUDA/Kokkos). **Adopt for cross-dataset eval.**
- **MonoCoder / LM4HPC** (Kadosh, Valero-Lara, Godoy et al., 2023-2024) — small HPC LMs, HPC-LLM survey.
- **PerfCodeGen** (arXiv:2412.03578, 2024) — performance-aware code generation.
- **Godoy et al. (ORNL/Argonne), "Evaluation of OpenAI Codex for HPC"** (2023-2024) — DOE-lab LLM evaluation.
- **Argonne AuroraGPT / ScienceGPT** (2024-2025, `NEEDS-VERIFY` for citable publications) — ALCF-based LLM-for-science program.

**Wedge**: no existing HPC-LLM work pairs a *compiler-verifier agent loop* with directive-based parallel. The OpenACC 100% / OpenMP 91.6% reproduction rate Fuzzlang has already achieved is a deployment-native differentiator.

## Compiler-error-repair benchmarks

- **DebugBench** (ACL 2024, arXiv:2401.04621) — 4253 bugs, 4 languages, execution-checked. No diagnostic-ID indexing.
- **GitBug-Java / BugsInPy** (pre-2024) — real-world.
- **No public benchmark is indexed by compiler diagnostic ID.** Fuzzlang can ship one as a supporting contribution.

## Bottom-line gaps Fuzzlang can own

1. **Diagnostic-ID as a dense, typed verifier signal.** Everyone else uses pass/fail or stderr text. Diagnostic ID is a 488-class structured label that lets the agent condition on *what kind of error remains*, not just "still broken". Natural fit for inference-time search / best-of-N / RLVR.

2. **Directive-based HPC is under-served and base-rate-poor.** LLMs have thin exposure to OpenMP/OpenACC diagnostics, so the inference-time compiler-verifier loop has more room to deliver a clean win than on vanilla C/C++ where base-rate is already high.

3. **Contamination-rigorous evaluation protocol for fuzzer-generated corpora.** Temporal holdout + AST-dedup + diagnostic-family stratified split + cross-compiler (GCC) transfer is missing from all prior compiler-error-repair work. Applying it directly answers the OOPSLA rejection.

**Direct methodological competitors to Fuzzlang v1's "fuzz → SFT → static eval" recipe**:
- WhiteFox (white-box fuzz, no SFT)
- RLEF (RL from execution, not diagnostics)
- OpenCodeInterpreter (execution-SFT, not compiler-specialized)
- HPC-Coder-v2 (domain SFT, no fuzzer generation)

**Nobody combines**: fuzzer-generated labels + diagnostic-ID structure + agent loop + HPC specialization. That is Fuzzlang v2's quadrant.
