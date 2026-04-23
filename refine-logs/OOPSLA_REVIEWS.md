# OOPSLA 2025 Reviews (verbatim)

Received 2025-06-10. All three reviewers voted "Reject - will argue to reject".
These are the **real** reviews; the verbal summary used in the first
research-refine cycle was paraphrased from memory and missed several of the
specific asks below. This document is the authoritative input for Round 6+.

---

## Review #584A

**Overall merit**: 2 — Reject - will argue to reject
**Reviewer expertise**: 3 — I know the material, but am not an expert

### Paper summary
This paper introduces two systems Fuzzlang Transformer and Fuzzlang Agent,
both for creating compilation error datasets. Fuzzlang Transformer generates
dataset entries by mutating real-world compilation commands and source code.
Fuzzlang Agent generates dataset entries based on error messages and source
code of Clang/LLVM tests. The paper also introduces a dataset generated
using Fuzzlang Transformer and Agent. The dataset significantly improved
(fine-tuned) the error repair capability of existing models such as
Llama3-8B and GPT-4o-mini.

### Detailed review (post-response)

The author response did not change my score because it did not address my concerns.

I believe that datasets like Fuzzlang-LLVM are useful for many types of PL/SE
studies and especially, as demonstrated in Section 5, help improve the error
repair capability of AI systems. Overall, I really like the ideas presented
in this paper.

However, I am afraid the paper is not ready to be accepted in its current
form because

- the paper does not provide enough details of the systems, dataset, and experiments, and
- the evaluation (Section 5) seems too preliminary to claim the dataset's strength.

#### Relation between Fuzzlang Transformer and Agent

While the paper presents the two systems as a single framework (e.g., "we
propose Fuzzlang, a framework for" in L183), I could not see the connection
between them. They do share the two base tools, Clang and Diagtool, but they
seem to share only a set of utility functions that does not quite constitute
a framework. Am I misunderstanding something here? In L324, the paper
mentions some connections between the two systems, but I could not figure it out.

#### Details of Fuzzlang Transformer/Agent

Unfortunately, I failed to understand the details of Fuzzlang
Transformer/Agent. I think I grasped their high-level overviews, but for
details, I have many questions. Some of them would be minor, but I would
like the authors to help me understand them.

- [L273. "The core innovation ... dynamically analyze and transform both the
  compilation commands and the source code during the build process."] What
  is dynamic in the analysis and transformation of commands and code? How is
  code transformation different from mutation?
- [Figure 2] Do the colored boxes enumerate all the mutation operations
  (transformation?) used in Fuzzlang Transformer? Either way, I highly
  recommend writing the details of those manually-crafted operations.
- [Section 3.2.2] I did not understand what LLM-driven transformers do at
  all. I would like the authors to provide more explanations possibly with
  an example. Furthermore, I cannot fully agree that "LLM-driven
  transformations can synthesize edge-case errors." I would like the authors
  to add the ground (e.g., prior studies) for this argument.
- [Section 3.2.3] Is the dataset (Fuzzlang-LLVM) in the JSON Lines format?
  Does Fuzzlang Agent create a dataset in this format too?
- [Section 3.2.4] Does this process merely undo a mutation (command/code
  transformation)? If so, it is exaggerated to refer to it as an automatic
  recovery mechanism.
- [Figure 3 and the itemization from p9] Do the error-generation,
  command-line, execution-and-analysis agents use LLMs? The figure
  illustrates them with the same icon as the code-reproduction agent, but as
  far as I understand, there is no room to use LLMs in the three agents. Am
  I misunderstanding something here?

#### Fuzzlang-LLVM dataset

I am unclear about the format of this dataset. I understand that it
includes a lot of information about compilation errors, but I do not see
its exact format.

- How is one error distinguished from another? Solely by diagnostic kinds?

#### Novelty

I am not convinced about the novelty of Fuzzlang Transformer/Agent. While
such systems may not have been developed before, I hesitate to call them
"novel" because I have not identified any fundamentally new ideas underlying
them. I really appreciate the effort made for those systems. They are
seemingly valuable. However, I am still not convinced about the novelty.

#### Evaluation

I am surprised by the significant improvement, but at the same time,
skeptical about the results. (It seems too high to me.) If the Fuzzlang-LLVM
dataset contains 660,000 entries of 488 distinct error types, the
validation set may include an entry very similar to the ones in the train
set, and thus, the LLMs achieved very high scores. In Section 5.1, the paper
says "The Fuzzlang-LLVM dataset was carefully partitioned." However, no
more details are provided, which made me skeptical about the significant
improvement. I think it would be better to measure the performance
before/after fine-tuning using other compilation error datasets.

#### Is the Data-Availability Statement reasonable?

No. This paper should include the data availability statement but it does
not. Please check the submission instructions
(https://2025.splashcon.org/track/OOPSLA#data-availability-statement).

#### Questions for authors

1. Do Fuzzlang Transformer and Fuzzlang Agent operate independently? (Relation)
2. Is there a key idea that led the authors to successfully develop Fuzzlang Transformer and Agents? (Novelty)

---

## Review #584B

**Overall merit**: 2 — Reject - will argue to reject
**Reviewer expertise**: 5 — This is my area

### Paper summary
Compilers are vital to software development, but research on compilation
errors remains limited. The authors propose Fuzzlang, a framework that
generates large datasets of compiler errors and an Agent leveraging LLMs to
analyze and isolate complex errors.

Fuzzlang produced five times more error types than DeepFix and covered
83.1% of LLVM/Clang's internal errors. Fine-tuning LLMs with Fuzzlang data
significantly boosted code repair results.

### Detailed review

**Strengths**:
- Well-written and easy to follow.
- Clear motivating examples provided.

**Weaknesses**:

1. The evaluation is limited by the use of relatively small models such as
   Llama3-8B and GPT-4o-mini. Without stronger baselines like GPT-4.5 or
   Claude's latest model, it remains unclear whether the improvements would
   hold against more capable models.

2. The evaluation relies entirely on fixing **synthetic** errors generated
   by the tool itself, raising concerns about whether the model can
   generalize to **real-world** compiler errors.

3. There is no comparison to existing methods such as **BIFI, DrRepair, and
   LaMirage** [1], which makes it very difficult to assess the results.
   This is another major concern for me.

   [1] LaMirage: Neurosymbolic Repair for Low-Code Formula Languages,
   OOPSLA 2022.

4. **Ground truth.** I am not convinced by the AI-based evaluation metrics
   shown in Figure 9. Without a more rigorous (manual) validation to
   confirm that a fix is indeed a "true fix", the reported precision
   numbers (on fixed rate) are questionable to me.

5. **Usability.** Finally, the paper does not address the potential harm
   from incorrect repairs it generates. Without a thorough safety analysis
   or user validation, the system's robustness for real-world usage remains
   completely unknown.

---

## Review #584C

**Overall merit**: 2 — Reject - will argue to reject
**Reviewer expertise**: 4 — I know a lot about this area

### Paper summary
This paper introduces two tools: Fuzzlang-Transformer and Fuzzlang-Agent.

Given as input C++ code and a compilation command, Fuzzlang-Transformer
injects errors into one of those two. It has various error injection
modules, including rule-based and LLM-based. Then, it collects data with
the compiler error message and the original and modified code. The authors
modified LLVM to report not just the raw error message but also an ID and a
name for the diagnosis. Running Fuzzlang-Transformer on LLVM itself yields
the Fuzzlang-LLVM dataset, comprising 660k error instances of 488 distinct
diagnosis IDs. Fine-tuning LLMs on 80% of that data dramatically improves
error repair performance on the remaining 20%.

Given as input the test suite of Clang itself, Fuzzlang-Agent returns as
output a reproduced error database. Internally, Fuzzlang-Agent uses four
components that are also referred to as "agents". Two of those comprise a
single LLM call each and the other two are rule-based (without LLM). The
result is 2,298 reproduced errors and 466 non-reproduced tests.

### Detailed review (post response)

My review remains unchanged because the response did not address my
questions and concerns.

### Original review

Fuzzlang stands out in that it covers a larger number of different error types.

I am concerned about the evaluation of Fuzzlang-Transformer. First, it is
only evaluated on a single codebase, **LLVM**, which is the same codebase
from which the training set is derived. While creating an 80%/20% train/test
split is good, it can still leak information. For example, instances in
both splits may be based on the **same function and the same fuzzing rule**.
This part of the paper would be stronger if the evaluation was on **an
entirely different codebase**. Furthermore, the evaluation should use
**real-world mistakes**, not just injected mistakes. Also, the authors went
to great lengths to go beyond raw error messages by adding IDs. It would be
good to include **an ablation to show their benefit**. Finally, the
evaluation uses an **LLM as a judge**. It would be more compelling to use
**code execution**.

The Fuzzlang-Agent is portrayed as containing multiple sub-agents. However,
only two of those use an LLM, and those are just single LLM calls, which
most people would not consider agents. Even the entire workflow is hardly
an agent, since the LLM does not act upon an environment by calling tools
and observing their output. The evaluation shows that given a test suite,
Fuzzlang-Agent returns a test suite with smaller coverage than its input.
For it to be useful, I would have expected it to improve upon its input in
some way. That does not become clear in the paper.

### Is the Data-Availability Statement reasonable?

Line 624 says "We will release the complete database on Hugging Face at the
time of the final submission". Here, "database" refers to auto-generated
Clang error documentation. Unless I missed it, there was no statement about
making the Fuzzlang-LLVM dataset dataset or the code for Fuzzlang itself
available.

### Questions for authors

1. Can you elaborate on exactly how you did the 80%/20% train/test split,
   and how you avoid contamination of functions or modules contributing to
   both?
2. How much do the added diagnostic ID and name contribute to the results,
   beyond just using raw error messages as-is?
3. When you say "demonstrating its ability to bridge gaps in current
   compiler testing tools" (L921), which gaps do you mean?

---

## Structured summary of concerns (for input to Round 6)

Grouping the distinct asks across three reviewers. An entry is marked
**"in plan"** if the current FINAL_PROPOSAL already addresses it, **"missing"**
if it does not, and **"covered by hybrid-eval change"** if the proposed
mutation+natural revision resolves it.

| # | Concern | Raised by | Status in current plan |
|---|---|---|---|
| 1 | Generalize to real-world (non-injected) errors | B, C | **partial** — NatErr exists but is natural-only and yields 100-500 instances. Hybrid eval covers both. |
| 2 | Evaluate on a different codebase than train | A, C | **missing** — LLVM-self-hosting study would share a codebase. Fix: train on mutations of project set X, eval on project set Y (disjoint). |
| 3 | 80/20 split mechanism — function/module contamination | A, C | **in plan** — project-level holdout + AST-hash dedup + diagnostic-family stratification + temporal holdout + contamination floor. Make it explicit in §method. |
| 4 | Diagnostic ID ablation — how much does it help beyond raw stderr? | C | **in plan** — DVCR − id vs DVCR − structure vs DVCR (3-way). Already causal. |
| 5 | Compare against prior repair methods (BIFI, DrRepair, LaMirage) | B | **missing** — no classical-repair comparator in current baselines. Add at least DrRepair (closest: compile-error repair). |
| 6 | Stronger / more-capable models | B | **partial** — 7B main + 32B appendix. Add Llama-3.3-70B or a frontier API model (GPT-5 / Claude-4.5 2026) as calibration in appendix. |
| 7 | LLM-as-judge is not rigorous; use code execution | B, C | **in plan** — compiler is the oracle; no LLM judge anywhere. Make this an explicit bullet in §methodology. |
| 8 | No safety/harm analysis for incorrect repairs | B | **missing** — add explicit limitations subsection: verified_fix_rate ≠ semantic-fix rate; appendix reports (compile_ok ∧ test_fail) if tests available. |
| 9 | Framework coherence (Transformer + Agent unclear) | A | **covered** — v2 has ONE headline mechanism (DVCR). Transformer is training-data-generation; Agent eval-curation. Clearly demoted. |
| 10 | Dataset format / data-availability statement | A, C | **missing** — commit to HuggingFace release URL + GitHub code URL in paper. Include NatErr audit manifest. |
| 11 | "Novel idea" is unclear | A | **covered** — v2 mechanism claim is typed diagnostic ID as inference-time verifier signal. Explicitly named. |
| 12 | Fuzzlang Agent "agents" aren't real agents | C | **covered** — v2 DVCR *is* a real agent (policy + observation + verifier + loop), not single LLM calls. |

### Derived decisions for Round 6

1. **Hybrid eval** (mutation + natural, per #1, #2). Mutation eval must use
   a different project set than whatever trains the B2/B3 baselines.
2. **Add DrRepair** (or a comparable classical compile-error repair method)
   as B_classical. Expected outcome: DrRepair underperforms; DVCR wins on
   both eval columns.
3. **Add Llama-3.3-70B appendix scale row**. Optional GPT-4.1 or Claude-4.5
   API as "frontier calibration" single-row.
4. **Explicit §Methodology subsection** on split mechanics answering A+C
   question #1 directly.
5. **Explicit §Limitations** on verified_fix_rate vs semantic-fix; add an
   appendix that subsets to test-covered files and reports (compile_ok ∧
   tests_pass) as an additional metric.
6. **Data availability**: commit to HF dataset URL + GitHub code URL, plus
   audit manifest release at submission.
