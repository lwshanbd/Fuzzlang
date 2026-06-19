# FuzzLang: implementation proposal and roadmap

*Target venue: CGO (submission September 2026).*

---

## 1. Vision

**FuzzLang is a compiler-diagnostic-driven method for constructing, and repairing against, a large-scale dataset of compilation errors.**

The compiler diagnostic is the organizing principle from end to end. It guides what data we generate (toward diagnostics we have not yet covered), it labels every record (each erroneous program carries the exact diagnostic it triggers), and it supervises repair (the diagnostic is the verifier signal an agent reacts to). Dataset and method are therefore not two projects. They are the same machinery pointed in two directions:

- pointed at construction, the machinery produces a broad, measured dataset of compilation errors;
- pointed at repair, the same machinery fixes errors using compiler feedback.

A dataset with no method is inert; a method with no dataset is unverifiable. FuzzLang is the claim that doing both, unified by the diagnostic, is what makes either one credible.

**A defining constraint.** FuzzLang constructs errors by introducing them into correct, compiling code. That is the meaning of the name. Every core record therefore has a correct origin by construction: a compiling version, plus the broken version derived from it. We never treat a standalone broken snippet (for example, a compiler regression test copied verbatim) as a record. Material that lacks a correct counterpart is not part of the core paired dataset; if it is collected at all, it lives in a clearly separated auxiliary split (see §5).

## 2. The contribution, in one sentence

> We can measure how much of a compiler's diagnostic space our dataset covers, guide generation to expand that coverage using the compiler's own tests and history, validate on real-world errors we did not create, and show that diagnostic-aware repair beats stderr-text and static fine-tuning, all at matched budgets.

This answers the two criticisms the project has faced before:

| Past criticism | FuzzLang's answer |
| --- | --- |
| "Your transformations are manual, artificial, small-scope." | A quantitative coverage metric over the compiler's full diagnostic space: measured, not hand-waved. |
| "Your evaluation is biased because you introduced the errors." | A real-world evaluation on genuine failing commits mined from open-source history. We did not create those errors. |

## 3. Success criteria

The project is judged by three numbers, in priority order:

1. **Diagnostic coverage:** the fraction of the compiler's diagnostic identifiers the dataset exercises, with a target multiplicity (each covered diagnostic represented several times, not once). This is the headline result.
2. **Verified repair rate:** the fraction of broken programs an agent fixes so that the compiler accepts the result, reported with confidence intervals and broken down by diagnostic family.
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
- What multiplicity target counts as "covered enough" (for example, at least three distinct examples)?

**Open questions.** The raw count is settled. What remains to agree is the diagnostic space we claim: do we report against every declared error, or a scoped subset (excluding unrelated subsystems, or restricting to reachable diagnostics)? And how do we avoid gaming the metric with trivial near-duplicate examples (this links to dedup in Foundation)?

**Dependencies.** Foundation (catalog and matcher). Drives GEN.

---

### Direction 2: GEN

> *Generate samples that target specific, currently-uncovered diagnostics.*

**Goal.** Expand coverage deliberately, not by luck. Move from "mutate code and hope we hit something new" to "we need diagnostic X, so produce an example of it."

**What it does.** Given a target diagnostic from the gap list, produce a record by introducing that error into correct, compiling code. This always yields a correct and broken pair plus the captured diagnostic. The strategies differ in how the error is introduced, never in whether a correct origin exists (it always does):

1. **Mechanical mutation:** cheap, high-volume perturbations of correct code. Good for breadth on common diagnostics; weak on rare or semantically specific ones. (This is what prior work relied on; here it becomes one supplier among several, not the whole story.)
2. **Guided mutation from the compiler's own evidence** (the primary new engine). For a target diagnostic, consult the compiler's regression test that exercises it and the commit that introduced it (the commit message and test files are rich context) to learn the precise code pattern that triggers it, then introduce that error into correct code, producing a correct and broken pair. The compiler's evidence guides what error to introduce and where; it is never copied in as a standalone broken sample. This is how we reach the long tail of rare diagnostics that blind mutation never hits.
3. **Model-assisted mutation:** a model introduces a targeted error into correct code (or writes a correct program and then breaks it), for diagnostics where rule-based mutation is too rigid. Useful for diversity and gap-filling.

Every generated candidate is verifier-checked: it enters the dataset only if the broken version triggers the intended diagnostic and the correct version compiles cleanly.

**Deliverables.** A generation service that takes a target diagnostic and returns validated records, plus a record of which strategy produced what, so we can report each strategy's contribution to coverage.

**Key decisions.**
- **Every record starts from correct code** and carries both versions. This is FuzzLang's defining constraint, not a tunable. Broken-only material is out of the core dataset (see §5).
- How much of the model budget goes to guided mutation versus model-assisted mutation.

**Open questions.** Mapping a diagnostic identifier to its introducing commit and its regression test is non-trivial, and the mapping may not exist for every diagnostic. What is the fallback when the compiler's history or tests do not yield usable context? How do we keep introduced errors realistic rather than degenerate?

**Dependencies.** Foundation (verifier). Consumes the gap list from COVERAGE and supplies records back. Shares synthesis machinery conceptually with REPAIR.

---

### Direction 3: REAL

> *Mine genuine compilation errors from real open-source projects.*

**Goal.** Provide an unbiased evaluation set, plus a stream of hard, real training data, that no one can dismiss as artificial, because the errors occurred naturally in real development.

**What it does.**
- Scans the commit history of buildable open-source projects for states that fail to compile, targeting commits that precede a "fix" commit, the natural sources of real breakage.
- Reconstructs the failing state and captures the real diagnostic or diagnostics it emits.
- Where a subsequent fix commit exists, recovers the corrected version, yielding a real (broken, fixed, diagnostic) triple.
- Feeds two consumers: an evaluation column of real errors, and, for cases the repair agent fails, new training records folded back into the dataset.

**Deliverables.** A harvesting pipeline producing real-world records with full provenance (project, commits, date), partitioned strictly away from any training data.

**Key decisions.**
- **Candidate projects** (buildable, active commit history, a mix of C and C++): LLVM/Clang, PostgreSQL, FFmpeg, SQLite, DuckDB, Redis, curl, Git, Qt, and Blender. A subset supplies training-side folded records; a disjoint subset is reserved purely for evaluation, so no project appears on both sides.
- How many projects to include for the core paper (breadth strengthens the generalization claim) versus how much per-project reproduction effort we can afford.

**Open questions.** Reproducing a historical failing build is operationally hard, since toolchains and dependencies drift. How much engineering do we invest per project, and how do we report the yield (failing commits found versus successfully reproduced)?

**Dependencies.** Foundation (verifier and catalog). Feeds REPAIR's evaluation and the dataset.

---

### Direction 4: REPAIR

> *Fix broken programs using compiler feedback, and show the diagnostic signal is what makes it work.*

**Goal.** Demonstrate the dataset's value and establish the method's core claim: **typed diagnostic feedback is a better repair signal than raw stderr text or static fine-tuning.**

**What it does.**
- Defines a repair loop: given a broken program and its diagnostic, a policy proposes edits; the verifier checks them; feedback (the new diagnostic, or success) drives the next attempt; the loop terminates on a verified fix, exhaustion, or a detected dead-end.
- Trains a policy on the FuzzLang dataset and compares it against a ladder of baselines and ablations:
  - a zero-shot model, a model with a stderr-text loop, a statically fine-tuned model, fine-tuning plus the loop, and the diagnostic-aware method;
  - causal ablations that withhold parts of the diagnostic signal (full diagnostic, versus structure without identity, versus raw stderr), to isolate what about the diagnostic helps.
- Evaluates on both the synthetic held-out column and the real-world column from REAL.
- Closes a loop with the dataset: failures (especially on real errors) become new records.

**Deliverables.** The repair results table (method versus baselines, two evaluation columns), the ablation result isolating the diagnostic's contribution, and a per-diagnostic-family analysis.

**Key decisions.**
- The fairness protocol: all methods compared at matched budgets (the same token and attempt envelope), so improvements cannot be dismissed as "just more compute."
- Which model or models to fine-tune given compute constraints. Model scale is supporting evidence, not the claim.

**Open questions.** A compile-clean fix is not always a correct fix. On the subset with tests, how do we measure that repairs preserve behavior, and how prominently do we caveat this?

**Dependencies.** Foundation (verifier and types). Consumes the dataset (from GEN) and the real column (from REAL). Shares synthesis machinery with GEN.

---

## 5. The dataset record

Every record, synthetic or real, conforms to one shape:

- **erroneous program:** the broken source;
- **corrected program:** the compiling version, present in every core record by construction. For generated records it is the correct origin the error was introduced into; for real records it is the fix commit;
- **compiler diagnostic:** the exact diagnostic or diagnostics emitted, with identifier, message, and location;
- **validated repair:** the edit transforming broken into corrected, verifier-confirmed;
- **provenance:** the origin (which generation strategy, or which project and commit), and the split it belongs to.

Records are deduplicated structurally rather than textually, to keep trivial near-duplicates from inflating coverage, and partitioned by project and source so training and evaluation never share provenance.

**Correct code is mandatory for the core dataset.** A record without a paired compiling version is not a FuzzLang record. If broken-only material is ever collected (for example, a real failure whose fix cannot be recovered), it is quarantined in a clearly labelled auxiliary split, never mixed into the core paired dataset and never counted as a paired training example.

## 6. How the pieces compose

- The Coverage and Gen loop is the construction engine: measure gaps, generate to fill them, re-measure. Coverage is both the metric and the controller.
- Real supplies the unbiased yardstick and the hardest data.
- Repair is at once the consumer that proves the dataset's worth and a producer, since its loop generates and validates fix data. Its diagnostic-as-signal claim is the method's intellectual core.
- Foundation is what lets all four agree on what a diagnostic is, what a compile result is, and what a record is.

Two evaluation columns keep the story honest: synthetic (held-out projects, strict isolation) and real (mined errors). A method that wins on both cannot be explained away by how we made the data.

## 7. Roadmap and phasing

Phased toward the CGO submission in September 2026, ordered by what each phase depends on.

| Phase | Focus | Output | Priority |
| --- | --- | --- | --- |
| **P0. Foundation** | Consolidate into one clean codebase: catalog, verifier, record format, config and tests | The substrate; reproducible builds | Core |
| **P1. Coverage engine** | Define the diagnostic space; measure current coverage; stand up the gap list | First real coverage number | Core (headline) |
| **P2. Guided Gen** | Target uncovered diagnostics via mutation and compiler-evidence-guided synthesis; drive coverage up | High-coverage dataset | Core (headline) |
| **P3. Dataset release** | Validation, dedup, splits, provenance, public release | The artifact | Core |
| **P4. Repair core** | Repair loop plus the key comparison (diagnostic-aware versus stderr baseline); fine-tune | Main repair result | Core (lean) |
| **P5. Real-world eval** | Mine one or more projects; evaluate both columns; fold failures back | Generalization result | Core (lean) |
| **P6. Ablations and scale** | Causal signal ablations, larger models, behavior-preservation check | Appendix strength | Optional |

For the September submission, P0 through P5 form the core of the paper: a measured, high-coverage, released dataset, the headline repair comparison, and a real-world evaluation on at least one project. The wider baseline ladder, causal ablations, and model-scale study in P6 add strength but are not required.

Coverage (P1 and P2) carries the most value and the most uncertainty, since the headline number lives there, so it starts first and gets the most room. P4 needs P2's dataset before it can begin. P5's harvesting is slow and operational, so it can run early and alongside the other work, since it does not wait on the dataset.

## 8. Risks and open questions

- **Coverage denominator definition.** The headline percentage is only as credible as the definition of "the diagnostic space." It must be principled and stated first.
- **Guided-generation context availability.** Not every diagnostic has a clean introducing commit or regression test; we need fallbacks and should report how often guidance was available.
- **Real-build reproduction cost.** Reconstructing historical failing builds is operationally heavy; per-project yield must be reported honestly.
- **Compile-clean is not correct.** Verified-fix is the primary metric, but behavior preservation needs a caveat and a tests-based spot check.
## 9. Where input is most wanted

1. The **scope of the diagnostic space** we claim coverage over. The raw count is mechanically derived from the compiler's diagnostic-definition files; what needs agreement is the subset we report against (see §4, Coverage).
2. The **multiplicity target:** how many distinct examples per diagnostic count as "covered enough."
3. The **project list** for real-world mining (a candidate set is proposed in §4, Real): which to include, and how to split them between training-fold and evaluation-only.
