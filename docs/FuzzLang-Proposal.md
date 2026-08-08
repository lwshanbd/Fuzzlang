# FuzzLang: implementation proposal and roadmap

*Target venue: CGO (submission September 2026).*

*Research framing revised July 2026; the executable experiment plan and gates
are maintained in `docs/plan.md`.*

---

## 1. Vision

**FuzzLang is a compiler-diagnostic-driven method for constructing a large-scale compilation-error dataset and demonstrating its value through repair fine-tuning.**

The compiler is both the knowledge source and the verifier. Its diagnostic definitions specify the error space, its emission sites and regression evidence describe trigger conditions, and its frontend validates every generated pair. FuzzLang distills that knowledge into reusable diagnostic-specific Injectors, applies them to correct code, and uses the resulting data to train repair models. Dataset and method are therefore not two projects. They are the same machinery pointed in two directions:

- pointed at construction, the machinery produces a broad, measured dataset of compilation errors from reusable Injectors;
- pointed at repair, fine-tuning and evaluation measure whether that dataset improves a model's ability to fix errors.

A dataset with no method is inert; a method with no dataset is unverifiable. FuzzLang is the claim that doing both, unified by the diagnostic, is what makes either one credible.

**A defining constraint.** FuzzLang constructs errors by introducing them into correct, compiling code. That is the meaning of the name. Every core record therefore has a correct origin by construction: a compiling version, plus the broken version derived from it. We never treat a standalone broken snippet (for example, a compiler regression test copied verbatim) as a record. Material that lacks a correct counterpart is not part of the core paired dataset; if it is collected at all, it lives in a clearly separated auxiliary split (see §5).

## 2. The contribution, in one sentence

> We can turn the compiler's own diagnostic knowledge into reusable Injectors, replay them on correct real-project code to build a broad and compiler-verified error dataset, and show under matched training budgets that fine-tuning an open model on this dataset improves repair on unseen and naturally occurring errors.

This answers the two criticisms the project has faced before:

| Past criticism | FuzzLang's answer |
| --- | --- |
| "Your transformations are manual, artificial, small-scope." | Diagnostic-specific Injectors are derived from compiler knowledge, replayed across real-project sources, and evaluated by quantitative coverage and transfer. |
| "Your evaluation is biased because you introduced the errors." | A real-world evaluation on genuine failing commits mined from open-source history. We did not create those errors. |

## 3. Success criteria

The project is judged by three numbers, in priority order:

1. **Diagnostic coverage:** the fraction of the compiler's diagnostic identifiers the dataset exercises, with a target multiplicity (each covered diagnostic represented several times, not once). This is the headline result.
2. **Fine-tuning gain:** the change in verified repair rate from the same open Gemma base model before and after matched-token SFT on FuzzLang data, including data-source ablations.
3. **Real-world generalization:** the verified repair rate on real failing commits from projects the model never trained on.

Everything else (model scale, additional languages) is supporting evidence, not the thesis.

## 4. The four directions

The work decomposes into four directions plus a shared Foundation that all four rest on. The Foundation is the main product of the codebase refactor; the four directions are the research.

```
                         ┌──────────────────────────────┐
                         │   FOUNDATION (shared)         │
                         │   diagnostic catalog ·        │
                         │   compiler verifier ·         │
                         │   dataset record format       │
                         └──────────────────────────────┘
                            ▲        ▲        ▲        ▲
                ┌───────────┘        │        │        └───────────┐
          ┌─────────┐         ┌─────────┐         ┌─────────┐    ┌─────────┐
          │ COVERAGE│ ◀─────▶ │   GEN   │         │  REAL   │    │ REPAIR  │
          │ measure │  loop   │ generate│         │  mine   │    │  fix    │
          └─────────┘         └─────────┘         └─────────┘    └─────────┘
                \                  /                   |              |
                 \________________/                    |              |
                   dataset (synthetic)         dataset (real) + eval column
```

### Foundation (cross-cutting, the refactor deliverable)

**Goal.** A single clean codebase replacing the current scattered scripts, providing the substrate the four directions share.

**What it provides.**
- A **canonical diagnostic catalog:** the authoritative list of the compiler's diagnostic identifiers (the denominator for coverage), each with its name, message template, and a matcher that recognizes that diagnostic in raw compiler output.
- A **verifier:** a uniform way to compile a program and obtain a typed result: does it compile, and if not, which diagnostic fired and where.
- A **dataset record format:** the schema every record conforms to (see §5), with validation, deduplication, provenance, and export.
- Configuration, logging, tests, and a reproducible build, replacing hardcoded paths and one-off notebooks.

**Why it is its own thing.** Without it, Coverage and Repair each re-derive "what is the set of diagnostics" and "how do I run the compiler," and the dataset format drifts. Naming it once keeps the four directions honest and interoperable.

---

### Direction 1: COVERAGE

> *Define the diagnostic space and measure how much of it the dataset covers.*

**Goal.** Turn "broad coverage" from a claim into a number, and drive that number up.

**What it does.**
- Establishes the **denominator:** the full set of in-scope diagnostic identifiers (from the catalog), with a principled filter for what counts (for example, user-facing C/C++ errors, excluding unrelated subsystems).
- Computes the **numerator:** which diagnostics the current dataset actually triggers, and how many times each.
- Reports coverage and multiplicity (how many distinct examples per diagnostic), and surfaces the gap list of uncovered or under-covered diagnostics.
- Feeds the gap list to GEN, then re-measures. This closed loop sits at the center of the methodology.

**Deliverables.** A reproducible coverage report (overall percentage, per-family breakdown, multiplicity distribution) and a live gap list that drives generation.

**Key decisions.**
- The **denominator is mechanically defined:** the set of error diagnostics declared in the compiler's diagnostic-definition files (TableGen) for the LLVM version we build against, extracted by a simple script. It is the authoritative count, with no hand-waving.
- The **paper headline scope is frozen:** strict C/C++ source diagnostics only.
  Starting from the 3,891 pinned TableGen errors, it excludes invocation or
  environment-only components and the audited name-level list of
  non-standard-dialect and hardware-target diagnostics. This yields the fixed
  1,935-diagnostic denominator. The full-catalog audit remains a transparent
  secondary operational metric for generation breadth.
- What multiplicity target counts as "covered enough" (for example, at least three distinct examples)?

**Open questions.** The raw count and paper scope are settled. What remains is
how to avoid gaming the metric with trivial near-duplicate examples (this links
to dedup in Foundation), and which secondary full-catalog breakdowns are most
useful to report.

**Dependencies.** Foundation (catalog and matcher). Drives GEN.

---

### Direction 2: GEN

> *Generate samples that target specific, currently-uncovered diagnostics.*

**Goal.** Expand coverage deliberately, not by luck. Move from "mutate code and hope we hit something new" to "we need diagnostic X, so produce an example of it."

**What it does.** Given a target diagnostic from the gap list, produce a record by introducing that error into correct, compiling code. This always yields a correct and broken pair plus the captured diagnostic. The strategies differ in how the error is introduced, never in whether a correct origin exists (it always does):

1. **Mechanical mutation:** cheap, high-volume perturbations of correct code. Good for breadth on common diagnostics; weak on rare or semantically specific ones. (This is what prior work relied on; here it becomes one supplier among several, not the whole story.)
2. **Direct compiler-evidence-guided mutation:** for a target diagnostic, consult its TableGen definition, compiler emission site, regression evidence, and history to learn the trigger pattern, then ask a model to introduce that error into correct code. Compiler tests are evidence only and are never copied in as final records. This existing per-record path remains a baseline and a long-tail fallback.
3. **Reusable Injector synthesis** (the primary new engine): ask a local Gemma model to distill the same compiler evidence into one diagnostic-specific Injector represented in **FuzzLang DSL**. Replay the Injector across many correct translation units and projects, validate every candidate, and amortize the model work over all accepted records.
4. **Hybrid long-tail generation:** use an Injector where the deliberately narrow FuzzLang DSL can express the transformation; otherwise use a direct Gemma edit, validate it, and attempt to distill the successful pair into a future Injector.

Every generated candidate is verifier-checked: it enters the dataset only if the broken version triggers the intended diagnostic and the correct version compiles cleanly.

**Deliverables.** A generation service that takes a target diagnostic and returns validated records; a versioned collection of reusable Injectors; and complete method labels so we can report each strategy's contribution to coverage, transfer, and generation cost.

**Key decisions.**
- **Every record starts from correct code** and carries both versions. This is FuzzLang's defining constraint, not a tunable. Broken-only material is out of the core dataset (see §5).
- FuzzLang DSL remains limited to token/context matching, identifier bindings, deterministic payload-local fresh names, byte-exact token-boundary normalization, and bounded local edits. General AST/type/scope transformation is not a prerequisite for the paper, and permissive literal payloads remain experimental until transfer is established.
- The final reproducible generation and repair pipeline uses a local open Gemma model rather than a paid API.

**Open questions.** Mapping a diagnostic identifier to useful emission sites and regression evidence is non-trivial, and the evidence may not exist for every diagnostic. How many diagnostics transfer through a narrow reusable Injector, when should the hybrid path fall back to a direct edit, and how do we keep introduced errors realistic rather than degenerate?

**Dependencies.** Foundation (verifier). Consumes the gap list from COVERAGE and supplies records back. Shares synthesis machinery conceptually with REPAIR.

---

### Direction 3: REAL

> *Mine genuine compilation errors from real open-source projects.*

**Goal.** Provide a smaller unbiased external-validity set that no one can dismiss as artificial, because the errors occurred naturally in real development.

**What it does.**
- Scans the commit history of buildable open-source projects for states that fail to compile, targeting commits that precede a "fix" commit, the natural sources of real breakage.
- Reconstructs the failing state and captures the real diagnostic or diagnostics it emits.
- Where a subsequent fix commit exists, recovers the corrected version, yielding a real (broken, fixed, diagnostic) triple.
- Supplies a project- and/or time-isolated evaluation column. A separate continual-learning experiment may fold earlier failures into training, but never contaminates the held-out column.

**Deliverables.** A formal NatErr release of roughly 100--300 high-quality paired failures from two or three projects, with full provenance (project, commits, date), compiler revalidation, and strict isolation from training data.

**Key decisions.**
- **Candidate projects** (buildable, active commit history, a mix of C and C++): LLVM/Clang plus one or two projects selected by reproduction feasibility. NatErr does not carry the paper's scale claim, so quality and isolation matter more than raw count.
- How many projects to include for the core paper (breadth strengthens the generalization claim) versus how much per-project reproduction effort we can afford.

**Open questions.** Reproducing a historical failing build is operationally hard, since toolchains and dependencies drift. How much engineering do we invest per project, and how do we report the yield (failing commits found versus successfully reproduced)?

**Dependencies.** Foundation (verifier and catalog). Feeds REPAIR's evaluation and the dataset.

---

### Direction 4: REPAIR

> *Fine-tune an open model and test whether FuzzLang data improves verified repair.*

**Goal.** Demonstrate the dataset's value: **under matched training-token and inference budgets, Gemma fine-tuned on FuzzLang data should repair more unseen compilation errors than the same base model and models trained on weaker construction baselines.**

**What it does.**
- Converts paired records into diagnostic repair examples and fine-tunes a local open Gemma model. For long real-project files, the primary target is a deterministic localized source-window rewrite that is spliced back into the complete translation unit before compiler verification; whole files are never silently truncated. An offset-based relative edit is retained as a representation ablation because it round-trips exactly but proved difficult for the model to generalize.
- Compares Gemma Base, Mechanical-SFT, DirectEdit-SFT, FuzzLang-SFT, and optionally a full Breadth+RealSource SFT arm under matched training-token and optimizer-update budgets. The Mechanical control is generated on correct real-project source for the main comparison; short self-contained Breadth programs are retained only as a domain-shift ablation.
- Evaluates on held-out translation units, an unseen project, diagnostic-tail slices, and the NatErr column from REAL.
- Reports verified fixes together with edit minimality, degenerate deletion rate, and behavior-preservation checks on a feasible subset.
- Retains the generic compiler-feedback repair loop as an evaluation mechanism. The typed-diagnostic-versus-stderr comparison is an exploratory negative result, not the intellectual core.

**Deliverables.** A matched-token SFT table, before/after Gemma results on RealSource and NatErr, data-source ablations, per-diagnostic-family and per-project analyses, and quality checks beyond compile success.

**Current feasibility evidence.** A single-seed 876-record Gemma 3 4B pilot on a fixed 32-example RealSource slice improved verified Fix@1 from 5/32 for the base model to 20/32 after SFT, while the offset-target SFT arm reached 0/32. The stricter construction-arm experiment now provides an initial controlled result. A zero-API LLVM run retained 297 RealSource-Mechanical pairs after 810 compiler invocations, with no test sources or missing corrected code. The Mechanical/DirectEdit/FuzzLang arms each contain 297 records, exactly 144,710 rendered tokens, and train for the same 57 optimizer steps; completion-token totals remain separately reported. They have no eval leakage and no cross-arm exact localized-input, pair, or record-ID overlap. On one 32-example, driver-correct LLVM slice, Base/Mechanical/DirectEdit/FuzzLang achieved verified Fix@1 of 5/5/15/16 and exact match of 0/1/6/11. FuzzLang and DirectEdit shared 13 compiler fixes, with three FuzzLang-only and two DirectEdit-only; FuzzLang's five additional exact matches were all one-sided. This supports the value of targeted generated data over the Mechanical control, but the one-fix FuzzLang-versus-DirectEdit gap is not evidence of repair-rate superiority. One compiler-clean DirectEdit output and one compiler-clean FuzzLang output share the same deletion-based quality flag. Larger project-isolated evaluation, multiple seeds, and behavior/NatErr columns remain required.

**Key decisions.**
- The fairness protocol matches training tokens, optimizer-update count, base checkpoint, LoRA recipe, and inference budget, and reports completion tokens separately, so improvements cannot be dismissed as "just more data or compute." Training remains unpacked because the available TRL+SDPA packing path risks cross-sample attention.
- Gemma is the common open model family for local Injector synthesis, SFT, and evaluation. Model scale is supporting evidence, not the claim.

**Open questions.** A compile-clean fix is not always a correct fix. On the subset with tests, how do we measure that repairs preserve behavior, and how prominently do we caveat this?

**Dependencies.** Foundation (verifier and types). Consumes Breadth and RealSource from GEN and the NatErr column from REAL.

---

## 5. The dataset record

Every record, synthetic or real, conforms to one shape:

- **erroneous program:** the broken source;
- **corrected program:** the compiling version, present in every core record by construction. For generated records it is the correct origin the error was introduced into; for real records it is the fix commit;
- **compiler diagnostic:** the exact diagnostic or diagnostics emitted, with identifier, message, and location;
- **validated repair:** the edit transforming broken into corrected, verifier-confirmed;
- **provenance:** the origin (including generation strategy and Injector ID, or project and commit), and the split it belongs to.

Records are deduplicated structurally rather than textually, to keep trivial near-duplicates from inflating coverage, and partitioned by project and source so training and evaluation never share provenance.

**Correct code is mandatory for the core dataset.** A record without a paired compiling version is not a FuzzLang record. If broken-only material is ever collected (for example, a real failure whose fix cannot be recovered), it is quarantined in a clearly labelled auxiliary split, never mixed into the core paired dataset and never counted as a paired training example.

The release is reported in three non-overlapping conceptual tiers:

- **FuzzLang-Breadth:** compiler-derived verified pairs optimized for diagnostic coverage; programs may be self-contained.
- **FuzzLang-RealSource:** generated errors injected into correct, non-test source from real projects; realistic source does not make these naturally occurring errors.
- **NatErr:** naturally occurring failures reconstructed from project history with their real fixes, reserved primarily for external-validity evaluation.

Coverage, scale, provenance, and repair results are reported separately for the tiers so injected real-source errors are never conflated with historical natural failures.

## 6. How the pieces compose

- The Coverage and Gen loop is the construction engine: measure gaps, generate to fill them, re-measure. Coverage is both the metric and the controller.
- Gen produces both FuzzLang-Breadth and FuzzLang-RealSource; the latter contains injected errors in non-test real-project code but is not called naturally occurring data.
- Real supplies NatErr, the smaller unbiased external-validity yardstick.
- Repair/SFT is the consumer intended to establish the dataset's value. The central downstream claim requires fine-tuning gain under matched budgets, not typed diagnostics outperforming stderr; the current single-arm pilot is feasibility evidence rather than completion of that claim.
- Foundation is what lets all four agree on what a diagnostic is, what a compile result is, and what a record is.

Two evaluation columns keep the story honest: injected RealSource errors from held-out projects under strict isolation, and naturally occurring NatErr failures. Improvement on both is harder to explain as an artifact of how the training data was generated.

## 7. Roadmap and phasing

Phased toward the CGO submission in September 2026, ordered by what each phase depends on.

| Phase | Focus | Output | Priority |
| --- | --- | --- | --- |
| **P0. Foundation** | Consolidate into one clean codebase: catalog, verifier, record format, config and tests | The substrate; reproducible builds | Core |
| **P1. Coverage engine** | Define the diagnostic space; measure current coverage; stand up the gap list | First real coverage number | Core (headline) |
| **P2. Injector Gen** | Distill compiler evidence into reusable FuzzLang DSL Injectors; compare against direct editing; drive coverage up on real-project source | High-coverage Breadth and RealSource datasets + Injector artifact | Core (headline) |
| **P3. Dataset release** | Validation, dedup, splits, provenance, public release | The artifact | Core |
| **P4. Gemma SFT** | Train matched-token Gemma arms on mechanical, direct-edit, and FuzzLang data | Main dataset-value result | Core |
| **P5. Natural-error eval** | Formalize NatErr from two or three projects and evaluate the frozen SFT arms | External-validity result | Core (lean) |
| **P6. Ablations and scale** | Compiler-evidence ablations, model scale, continual learning, wider behavior-preservation checks | Appendix strength | Optional |

For the September submission, P0 through P5 form the core of the paper: measured high-coverage datasets, a reusable Injector artifact with a direct-edit comparison, a matched-token Gemma SFT result, and a smaller natural-error evaluation. Wider evidence ablations, continual learning, and model-scale studies in P6 add strength but are not required.

**Execution checkpoint (2026-08-07).** The current priority is no longer
unbounded Injector expansion. After the already-submitted target-only replay
chains finish, FuzzLang will freeze a canonical strict release audit. Further
generation is permitted only if that audit remains below the predeclared
`+300 diagnostic types relative to batch 6` target. The remaining schedule
is reserved for the evidence the paper actually needs: a matched
Injector-versus-DirectEdit experiment, project-isolated RealSource evaluation,
matched-token Gemma SFT with multiple seeds, and formal NatErr external
validity. This keeps dataset size from displacing the experiments required to
establish dataset value.

Coverage and Injector generation (P1/P2) carry the main novelty, but P4 starts in parallel with a small SFT smoke so that FuzzLang DSL engineering cannot block the downstream evidence. P5 harvesting is slow and operational, so it runs early but has a bounded 100--300-record goal.

## 8. Risks and open questions

- **Coverage denominator enforcement.** The frozen 1,935-diagnostic strict
  C/C++ code scope must be recomputed from the pinned catalog, invocation
  components, and audited exclusion list for every release; the 3,891-type
  full-catalog figure is supplementary only.
- **Guided-generation context availability.** Not every diagnostic has a clean introducing commit or regression test; we need fallbacks and should report how often guidance was available.
- **FuzzLang DSL scope.** A general AST/type transformation language would consume the schedule. Version 1 remains a single-site lexical language, adds only fresh local names and safe token normalization, and falls back to recipe plus direct Gemma editing if cross-project transfer fails.
- **Gemma training risk.** Gemma-4-31B inference works locally, but its FSDP LoRA path is incompatible with the current Tioga kernel/runtime stack. The planned fallback is active: Gemma 3 4B has completed bounded smokes, a three-epoch 876-record run, adapter reload, and compiler-verified base/SFT evaluation. ROCm activation-checkpoint recomputation failed on variable-length batches, so the successful pilot disabled activation checkpointing and archived that choice. The strict three-arm training and 32-example compiler evaluation have now completed after an ECC-node retry and a uniform memory-safe microbatch change (`batch_size=1`, gradient accumulation 2). Model scale is not part of the claim; the remaining risk is scaling the result to multiple seeds and unseen projects.
- **RealSource sequence length and repair representation.** Whole real-project translation units often exceed the training context window. Both implemented localized targets reconstruct a complete source file and reject silent truncation. The offset form fits all 2,318 current records but produced 0/32 held-out fixes in the controlled pilot; the bounded window-rewrite form produced 20/32 and is now primary. Its length guarantee must be rechecked for every future release.
- **Real-build reproduction cost.** Reconstructing historical failing builds is operationally heavy; per-project yield must be reported honestly.
- **Compile-clean is not correct.** Verified-fix is the primary metric, but behavior preservation needs a caveat and a tests-based spot check.
## 9. Where input is most wanted

1. The **project list** for RealSource transfer: which buildable C++ and C projects can provide stable compile databases and enough non-test translation units.
2. The **Gemma SFT configuration and matched-token arms** after the 32/128-example smoke establishes a stable local training path.
