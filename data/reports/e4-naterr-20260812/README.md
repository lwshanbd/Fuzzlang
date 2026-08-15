# E4 — NatErr: errors FuzzLang did not create. Status 2026-08-12

NatErr answers the one objection every other FuzzLang result invites: the model
is trained on errors FuzzLang made and evaluated on errors FuzzLang made. NatErr
takes errors *developers* made, recovered from commit history, and verified by
the same pinned Clang.

**Status: the pipeline is complete, tested, and now correct; the release is
3 verified paired records against a target of 100–300.** Scale-up is blocked by
one measured obstacle with a known price, stated below. Nothing here lowers a
gate to inflate the number.

## 1. Natural compile errors are scarce — and that is a finding

Fix-build commits (`fix|repair|unbreak` × `build|compil*|cmake|ninja|linker`)
over each project's full local history:

| project | commits | fix-build commits | usable |
|---|---:|---:|---|
| **llvm** | 565,548 | **2,039** (since 2022-06) | yes |
| ffmpeg | 125,767 | 81 (all time) | no |
| abseil | 3,508 | 3 | no |
| json-c | 1,469 | 2 | no |
| leveldb | 447 | 2 | no |

Outside a very large, very high-velocity project there is essentially nothing to
mine. json-c yields two candidates in eleven years. **This is the argument for
FuzzLang stated in someone else's data:** if naturally occurring compilation
errors were abundant and cheap to recover, a construction framework would not be
needed. They are not, so it is.

It also fixes the project choice. LLVM is the only viable source, and LLVM is
also the largest contributor to the training corpus — so isolation has to be
enforced explicitly rather than obtained by picking a different project.

## 2. Yield funnel, measured

```
2,039  fix-build candidates (llvm, 2022-06-01 .. 2026-08-12, all SHAs reachable)
  682  fix touches exactly one source file and no header  ("self-contained")
  163  predecessor version fails to compile with a typed primary diagnostic
    3  fix side also compiles clean under the same command  → ACCEPTED
```

Rejections at the final gate (163 → 3): `corrected_not_clean` 142,
`test_source` 20. The `test_source` drops are correct and permanent — Clang
regression tests are never records.

The accepted three, all isolated from the SFT training arms:

| source | diagnostic |
|---|---|
| `llvm/tools/llvm-pdbutil/DumpOutputStyle.cpp` | `err_ovl_no_oper` |
| `llvm/lib/Analysis/LazyCallGraph.cpp` | `err_member_decl_does_not_match` |
| `llvm/lib/Transforms/IPO/Inliner.cpp` | `err_no_member` |

## 3. What blocks scale-up: header drift, quantified

`corrected_not_clean` is not a gate that is too strict. It is one assumption
that does not hold: **a file from 2023 does not compile against a header tree
from 2026.** Compiling one historical file against a frozen build tree is only
valid when the whole tree matches, and it never does.

Causes, over the 142 rejections:

| cause | n | what it really is |
|---|---:|---|
| `no member named` / `out-of-line definition does not match` | 41 | the declaring header moved on |
| header not found | 38 | header added or deleted since |
| undeclared identifier | 11 | API renamed since |
| other (macro arity, deleted constructor, overload sets) | 52 | same drift, different symptom |

Materializing the *source* header tree at the predecessor commit
(`git archive <sha> llvm/include clang/include <dir>` onto tmpfs, **0.9 s**,
against 41 s on the parallel filesystem) fixes most of it and was validated on a
30-candidate pilot. Two things changed:

- 7 of 30 candidates flipped to **`buggy_became_clean`** — the "error" was never
  real, it was drift in our own reconstruction. Those seven were false positives
  in the old 163, and the materialized tree is what exposed them.
- The residue is **TableGen-generated `.inc`** files, which still come from the
  frozen build: `no member named 'vector_splice' in namespace 'llvm::Intrinsic'`
  (`IntrinsicEnums.inc`), `no member named 'OPT_fno_modules_reduced_bmi'`
  (`Options.inc`), macro-arity errors from generated `.def` files. Those cannot
  be recovered with `git archive`; they require running the build at that
  commit.

## 4. The price of finishing, measured rather than guessed

The 163 reproducible candidates are spread over roughly 50 months. **Zero fall
within ±6 weeks of the current build commit** (`ca7933e`, 2026-04-29) — so one
snapshot build buys almost nothing, which is exactly why the current yield is 3.

At ~3.3 candidates per month, a snapshot build valid for a ±6-week window covers
~10 candidates, of which roughly half should survive the pairing gate:

> **≈5 records per LLVM build. 100 records ≈ 20 builds ≈ 30 node-hours**,
> parallelisable across ~5 nodes into one evening.

That is the honest cost of a 100-record NatErr, and it is the plan's own
prescription — "a full historical checkout plus a relocatable or reconstructed
compile environment" — with a number attached.

## 4b. The snapshot campaign: built, costed, and re-costed by measurement

The plan in §4 was implemented (`real/run_naterr_snapshot_campaign.sh`,
`real/naterr_snapshots.py`, `real/run_naterr_plan.py`) and then corrected three
times by what it measured. Each correction is worth recording, because each one
would otherwise have been a silent multiplier on the cost.

**A build is much cheaper than assumed — 14 minutes, not an hour.** Only the
TableGen targets are needed, not a full clang. On tmpfs: `git archive` of
llvm+clang+mlir 90 s, cmake configure ~10 min, TableGen ~4 min. The 10-minute
configure now dominates.

**The compile database, not the build's age, was the first bottleneck.** A
`clang;X86` build compiles 3,380 TUs and addresses only **172 of 682**
candidates. Most LLVM fix-build commits are for subprojects we do not build
(mlir 85, lldb 85, flang 57, compiler-rt 41, libc 18) or for other targets. Adding
`mlir` and four more targets raises the database to 4,819 TUs and addressability
to **263 of 682**. A further 17% of candidates name a configuration we can never
reproduce under Linux/clang at all — "fix MSVC build", "fix build with gcc
7.5.0", "fix bazel build".

**Per-target TableGen is separate and mandatory.** Without
`<Target>CommonTableGen`, every `llvm/lib/Target/**` TU fails on a missing
`<Target>Gen*.inc`. It costs 78 s and the target names are now discovered from
`make help` rather than hardcoded, since the enabled set follows `TARGETS` and
the naming has drifted over four years.

**And then the window itself turned out to be the binding constraint.** With a
±21-day snapshot, all three reproduced candidates still failed:
`out-of-line definition of 'isReMaterializableImpl' does not match any
declaration`, `unknown type name 'DependentTemplateSpecializationTypeLoc'`.
Three weeks of LLVM churn is enough to break source/header correspondence.
Materializing the *source* headers per candidate while keeping the snapshot's
`.inc` does not rescue it either — the generated `.inc` drifts too
(`use of undeclared identifier 'IsX32'` from `X86GenInstrInfo.inc`). A fourth
candidate flipped to `buggy_became_clean` under the sharper environment: another
artifact of our own reconstruction, exposed rather than counted.

So the environment has to match the candidate's own commit, and the campaign
re-costs accordingly:

| window | snapshots | node-hours | wall at 4 nodes |
|---:|---:|---:|---:|
| ±21 days | 41 | 9.6 | 2.4 h |
| ±7 days | 102 | 23.8 | 6 h |
| **±3 days** | **197** | **46** | **11.5 h** |
| exact commit | 489 | 114 | 28 h |

Everything needed to run it is checked in and the plan is deterministic
(`data/natErr/snapshot-plan.json`, greedy set cover, densest cluster first, so a
campaign cut short still spent its builds well). `run_flux_naterr_campaign.sh`
shards it round-robin across nodes.

## 4c. The campaign should not be run, and here is why

Before spending 46 node-hours, the assumption underneath the whole funnel was
tested directly: **does a fix-build commit's predecessor actually fail to
compile, when compiled in its own environment?**

Two tests, both negative:

- **Exact predecessor commit.** LLVM configured and TableGen'd at
  `c924e7a8672f` — the parent of *"[llvm] Fix X86InstrInfo.cpp build after
  \#160188"*, a one-line fix to a single file. Result: `no_error`. The file
  compiles cleanly. The fix was `+#include <atomic>` — a real build break, on a
  standard library that does not pull `<atomic>` in transitively. Ours does.
- **±3-day window, near-matching build.** 5 candidates: 3 not in the compile
  database, **2 compile cleanly, 0 reproduce.**

So the 163 "reproduced" candidates in §2 were, in the main, **artifacts of
compiling historical source against a mismatched header tree** — the same
mechanism that flipped candidates to `buggy_became_clean` the moment the
environment got sharper. Sharpening it further drives the reproduction rate
toward zero, not toward a larger record set.

**The mechanism is structural, and it is the real finding.** A large project's
pre-merge CI already covers the mainstream configuration. What therefore
survives into `main` and needs a follow-up "fix build" commit is precisely what
mainstream CI does *not* cover: another compiler (MSVC, GCC 7.5), another
standard library, another platform (NVPTX, AIX, Windows), another build system
(bazel). 25% of the 682 say so in the subject line or add nothing but an
`#include` or an `#ifdef`; the `<atomic>` case above is exactly this and its
subject line gives no hint.

> Mining natural compilation errors is not only **scarce** (§1: json-c yields
> two candidates in eleven years) — it is **environment-bound**. Reproducing a
> natural build break means reproducing the configuration it broke in, so the
> cost scales with configuration diversity, not with history depth. Building at
> the right *commit* is necessary and nowhere near sufficient.

**Recommendation: do not run the campaign.** It would spend 46 node-hours
establishing that these candidates do not fail under our configuration. The
scripts stay checked in because the finding above is what they measured, and
because a future NatErr attempt should start from a different premise — mine
for errors reproducible in *one fixed* configuration, rather than for commits
whose message says "fix build".

Evidence for this recommendation is 6 candidates tested in a correct
environment, not 682. What would settle it beyond doubt is a full campaign; the
point is that the same 46 node-hours are better spent elsewhere, and that the
expected return has been measured rather than assumed.

## 5. Three defects found and fixed

1. **`-Werror` discarded 240 of 269 candidates.** LLVM builds with `-Werror` and
   passes GCC-only suppressions (`-Wno-class-memaccess`); Clang answers with
   `-Wunknown-warning-option`, which `-Werror` promotes to an error, so the
   *fixed* revision failed to compile and the pair was thrown away. NatErr asks
   whether source has a compilation error, not whether it satisfies a warning
   policy. Fixed in `_build_clang_argv`, which now sanitises before the command
   is stored — the command in the record is the one under which the pair
   reproduces. Test: `src/real/tests/test_reproduce_stage2_llvm.py`.
2. **The archived Stage-1 manifest was unusable.** 672 of its 856 SHAs no longer
   exist in `main`: GitHub squash-merges rewrote them. Re-harvesting from the
   local checkout makes every candidate reachable by construction.
3. **Formalization was serial**, at two whole-TU compiles per row. Added
   `--jobs` (threads, since the cost is subprocess I/O and the verifier holds no
   per-call state), with a test asserting the output is byte-identical at any
   worker count.

## 6. Isolation from training data

LLVM is both the only viable NatErr source and the largest training project, so
`real/naterr_isolation.py` enforces **file-level** isolation: a NatErr record is
dropped if the model saw any revision of the same file in the same project.

| training set compared against | records | isolated | overlap |
|---|---:|---:|---:|
| the three SFT arms (875 files) | 3 | **3** | 0% |
| the entire E1 generation pool (4,194 files) | 3 | 1 | **67%** |

The current release is clean against what was actually trained on. The second
row is the warning: a larger SFT run drawing more of the E1 pool would collide
with two of these three, so this gate must run against the *actual* arms of
whatever run NatErr is used to evaluate — not once, now.

## 7. Reproduce

```bash
# 1. harvest (both refs; the local checkout's history is split at 2026-06-20)
PYTHONPATH=src python3 -c "
from pathlib import Path
from real.harvest import NatErrProject, harvest_metadata, write_manifest
repo=Path('external/llvm-project'); seen=set(); merged=[]
for ref in ('HEAD','origin/main'):
    for c in harvest_metadata(NatErrProject('llvm','x',ref), repo, since_iso_date='2022-06-01'):
        if c.fix_sha not in seen: seen.add(c.fix_sha); merged.append(c)
write_manifest(sorted(merged, key=lambda x: x.commit_date_iso),
               Path('data/natErr/manifest_llvm_wide_20260812.jsonl'))"

# 2. reproduce
PYTHONPATH=src python3 src/real/reproduce_stage2_llvm.py \
  --manifest data/natErr/manifest_llvm_wide_20260812.jsonl \
  --llvm-src external/llvm-project --build-dir /p/lustre2/shan4/fuzzlang-llvm-build \
  --clang-bin /p/lustre2/shan4/fuzzlang-clang/bin/clang \
  --diagtool-bin /p/lustre2/shan4/fuzzlang-clang/bin/diagtool \
  --out data/natErr/llvm_wide_20260812.jsonl \
  --summary-out data/natErr/llvm_wide_20260812.summary.json --skip-build --jobs 24

# 3. pair, revalidate, emit canonical Records
PYTHONPATH=src python3 src/real/run_formalize_naterr.py \
  --input data/natErr/llvm_wide_20260812.jsonl \
  --project llvm --project-checkout external/llvm-project \
  --clang-bin /p/lustre2/shan4/fuzzlang-clang/bin/clang \
  --diagtool-bin /p/lustre2/shan4/fuzzlang-clang/bin/diagtool \
  --out data/natErr/formal-20260812/records.jsonl \
  --rejected-out data/natErr/formal-20260812/rejected.jsonl \
  --manifest-out data/natErr/formal-20260812/manifest.json --jobs 32 --timeout 180
```

## 8. Artifacts

- `data/natErr/manifest_llvm_wide_20260812.jsonl` — 2,039 reachable candidates
- `data/natErr/manifest_llvm_selfcontained.jsonl` — the 682 single-file subset
- `data/natErr/llvm_wide_20260812.jsonl` + `.summary.json` — 269 reproduced
- `data/natErr/formal-20260812/` — records, rejections with reasons, manifest
- `data/natErr/formal-20260812/records-union.jsonl` — the 3 accepted records
- `data/natErr/snapshot-plan.json` — the deterministic 41-snapshot build plan
- `harvest_yield.csv`, `funnel.csv`, `rejection_causes.csv` — the tables above
- `environment_sensitivity.csv` — reproduction rate as the compile environment
  is sharpened from four years off to the exact commit
- `fix_commit_classification.csv` — what the 682 fix commits actually change

## 9. What this does and does not license

It does **not** support an external-validity claim: three records cannot carry
one, and §4c shows that more builds would not produce many more.

What it does support, and what belongs in the paper, is a two-part measured
claim about why a construction framework is needed:

1. **Natural compilation errors are scarce.** Fix-build commits over full
   history: llvm 2,039, ffmpeg 81, abseil 3, json-c 2, leveldb 2 (§1).
2. **They are environment-bound.** Reproduction rate falls toward zero as the
   compile environment is sharpened toward the commit's own, because the
   breaks that survive a large project's CI are the ones its CI does not
   cover — another compiler, another standard library, another platform (§4c).
   Reproducing them costs a configuration matrix, not a git checkout.

Together these say the supply of naturally occurring, reproducible compilation
errors is small and expensive in a way that does not improve with effort — which
is the case for constructing them instead.

The pipeline is correct and every gate it applies is one the paper would have to
apply anyway; it is checked in and reusable. What is *not* recommended is
scaling this particular mining premise. A future NatErr attempt should invert
it: fix one configuration, then search history for errors reproducible *in that
configuration*, rather than starting from commits whose message says "fix
build".
