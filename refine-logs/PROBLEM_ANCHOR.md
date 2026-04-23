# Problem Anchor (frozen, immutable)

> This anchor is copied verbatim into every round. If reviewer feedback would require changing any line below, that is **drift** and must be called out, not silently accepted.

## Bottom-line problem
LLM-based code repair for **compilation errors emitted by production C/C++/directive-parallel compilers** is still unreliable at the level demanded by real build systems. A model that scores well on synthetic benchmarks still fails on real errors from real projects, and "fine-tune a bigger dataset" has reached a clear diminishing-returns point once data isolation is enforced. The compiler itself — which produces the error and can verify any proposed fix for free — is treated as a passive data source rather than an active, loop-closing signal.

## Must-solve bottleneck
The compiler's own **diagnostic output (diagnostic ID + message + location)** is the cheapest, most precise ground-truth signal in existence for code-repair correctness, but today's LLM repair pipelines do not close the loop on it. Specifically:

1. Fine-tuned models are trained on (buggy_code, error, fixed_code) triples and evaluated with LLM-as-judge or string-equivalence — **no compiler-in-the-loop verification at inference time**.
2. Agent repair work (SWE-agent, Agentless, AutoCodeRover) closes the loop with unit tests but largely ignores the richer, per-token, per-diagnostic signal the compiler already emits.
3. As a result, the reported gains from fine-tuning shrink dramatically once (a) train/test mutations come from the same project (data isolation) and (b) evaluation uses the compiler as oracle rather than a sibling LLM judge.

## Non-goals
- Building a general-purpose coding agent that competes with SWE-agent on SWE-bench. Scope is **compilation errors**, not arbitrary bug-fix tasks.
- Runtime / semantic bug fixing via test execution. The compiler diagnostic is the oracle; we do not claim to fix logic bugs that compile.
- Beating SOTA on HumanEval / MBPP style benchmarks. These measure code generation from spec, not repair.
- Inventing a new LLM architecture or proposing a new pre-training objective.
- Producing yet another synthetic error dataset as the main contribution.

## Constraints
- **Venue**: NeurIPS 2026 (ML/agent or Datasets & Benchmarks track). Writing and evaluation must be rigorous enough for ML reviewers, not systems reviewers.
- **Compute**: Polaris @ Argonne National Lab (NVIDIA A100 40GB, 4 GPUs per node). Project allocation `diomp`. Scaled experiments possible but must be justified.
- **Models accessible**: open-weights (Llama 3.1/3.3, Qwen2.5-Coder, DeepSeek-Coder-V2/V3, StarCoder2), closed API (GPT-4o/4.1, Claude 3.5/4, Gemini 2.x) as a calibration point only. Prefer open for reproducibility.
- **Existing assets** (must leverage, not rebuild):
  - Modified Clang that emits diagnostic ID alongside message (rare, load-bearing).
  - Modified `diagtool` with `find-diagnostic-name`.
  - 660k Fuzzlang-LLVM error corpus, 488 diagnostic types.
  - Fuzzlang Agent pipeline for error reproduction from `llvm-lit` tests.
  - Fuzzlang Transformer (compiler wrapper, integrates into any Clang build).
  - Author domain expertise in directive-based parallel (OpenMP/OpenACC), documented in Shan, Araya-Polo, Chapman 2024 (ref [15]).
  - Perfect Fuzzlang Agent reproduction on OpenACC (100%) and OpenMP (91.6%) → natural specialization domain.
- **Time budget**: next-cycle NeurIPS 2026 deadline (approx May 2026 abstract / May 2026 full paper). Full-paper-quality experiments within ~4 weeks of method freeze.
- **Hard methodology rules** (dictated by OOPSLA rejection):
  - **Data isolation**: no train/test pair may share the same source file, same mutation family, or near-duplicate error context. Splits must be at the project-level and diagnostic-family-level, not 80/20 random.
  - **No LLM-as-judge on identical model family**: all correctness claims must be verified by the compiler itself, not by a sibling LLM.
  - **Ablations required**: each claimed mechanism must have a drop/swap ablation.
  - **Baseline comparisons required**: at least one strong agent baseline (e.g., Self-Debug-style iterative prompting) and one strong non-agent baseline (vanilla fine-tuning).
  - **Contamination audit**: report LLM's base-rate ability on Fuzzlang-LLVM before any fine-tuning, and report model-family × training-cutoff interaction.

## Success condition
Reviewers of NeurIPS 2026 would be convinced that:

1. **Mechanism claim**: Using the compiler's own diagnostic ID as an inference-time verifier and (optionally) reward signal yields a measurable, decisive improvement over both (a) static fine-tuned repair and (b) generic test-feedback agents, on code-repair tasks where the compiler is the natural oracle.
2. **Evidence claim (revised 2026-04-23 after reviewing the actual OOPSLA reports)**: The improvement holds **under both rigorous mutation-based evaluation and natural-error evaluation**, and survives full data isolation (project-level holdout, temporal holdout, AST-hash dedup, diagnostic-family stratification, compiler-only oracle, no LLM judge). "Real-world" per OOPSLA Reviewer C = "not just injected" — mutations may appear in evaluation if they use disjoint projects and strict dedup; naturals must also appear to directly address the "scores well on synthetic but fails on real" concern.
3. **Domain claim (optional but valuable)**: For HPC / directive-based parallel code (OpenMP/OpenACC) — a setting where Fuzzlang's compiler-native infrastructure is uniquely positioned — the approach enables practically useful repair at a quality level reachable nowhere else.

The paper is successful only if it passes those three tests.

## Evidence standard (added 2026-04-23)

Based on verbatim OOPSLA reviewer text in `OOPSLA_REVIEWS.md`, the following are **required** (not optional) ingredients of the evaluation protocol:

- **Two evaluation regimes in the main table**: mutation (Fuzzlang-Transformer, with strict project-level holdout) AND natural (NatErr). The "natural-only" position from Rounds 3-4 was a reading of the old paraphrased critique; the real reviewers want to see robustness across both.
- **Cross-codebase evaluation**: train on project set X, evaluate on project set Y (disjoint). Same-codebase eval is insufficient per Reviewer C explicit ask.
- **Classical-repair baseline**: at least one method from the BIFI / DrRepair / LaMirage family, per Reviewer B.
- **Stronger-model calibration row**: at least one frontier-scale (70B open or closed-API frontier) evaluation in the appendix, per Reviewer B.
- **No LLM-as-judge anywhere**: compiler verifies. Any secondary check (e.g., tests) is a real executor, not an LLM. Per Reviewer B and C.
- **Diagnostic-ID ablation is load-bearing**: Reviewer C asked for this directly. Already in DVCR − id. Must be in main table, not appendix.
- **Explicit split mechanics**: subsection of methodology must answer "how is contamination avoided across functions/modules" per Reviewer A and C.
- **Explicit limitations section**: verified_fix_rate measures compile success, not semantic correctness. Report (compile_ok ∧ tests_pass) as a secondary metric on the test-covered subset. Per Reviewer B.
- **Data + code availability statement**: commit to HuggingFace dataset URL + GitHub code URL + NatErr audit manifest. Per Reviewer A and C.

## Drift detectors (to catch in later rounds)
The following would each indicate silent drift from this anchor:
- Main contribution becomes "a bigger/better dataset" rather than "a method that uses the compiler as a verifier".
- Evaluation retreats to LLM-as-judge or 80/20 random splits on the same LLVM corpus.
- Domain scope silently expands back to "all compilation errors in all languages" and loses sharpness.
- Fuzzlang Agent re-centered as the primary contribution when it is a supporting data-generation component.
- Adding a second parallel contribution (e.g., "and also a new pre-training objective") to boost perceived substance.
