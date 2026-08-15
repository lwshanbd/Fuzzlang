# E1 — Construction reach and cost, 2026-08-08

> **Superseded for all counts by
> [e1-construction-20260812-devendored](../e1-construction-20260812-devendored/README.md).**
> Every number below attributes fetched dependencies to the project that
> fetched them: duckdb and protobuf vendor Abseil and others under
> `build/_deps/`, which the clean-source gate of the time did not reject. The
> recount drops 2,090 of 15,097 records (duckdb 1,941 → 167, protobuf
> 1,199 → 891). The claims survive — 13,007 records, 514 diagnostics, 13
> projects, 395 at multiplicity ≥ 3, still zero model calls — but **cite the
> 08-12 report, not this one.** The method, protocol, and configuration finding
> below remain accurate.

The released FuzzLang Injector library applied to correct, non-test source from
13 real projects. **Zero model calls and zero GPU hours in every arm**; the only
cost is compilation, on one CPU node.

Reproduce:

```
PYTHONPATH=src python3 src/gen/realcorpus/run_freeze_source_splits.py \
  --pool <each clean pool>/sources.jsonl \
  --held-out-project abseil --held-out-project ffmpeg \
  --held-out-project leveldb --held-out-project json-c \
  --eval-fraction 0.15 --seed 20260808 \
  --out-dir data/gen/source-pools/e1-splits-v0001 \
  --manifest-out data/gen/source-pools/e1-splits-v0001/split-manifest.json

MAX_PER_DIAG=25 bash src/gen/fuzzlang_dsl/run_e1_library_replay_arms.sh

PYTHONPATH=src python3 src/gen/fuzzlang_dsl/run_e1_construction_report.py \
  --run-dir data/gen/experiments/e1-library-replay-v0001 \
  --canonical-map data/reports/strict-injector-coverage-20260807-canonical/diagnostic_record_map.csv \
  --report-out data/gen/experiments/e1-library-replay-v0001/e1-construction-report.json \
  --table-out data/reports/e1-construction-20260808/arm_table.csv \
  --per-project-out data/reports/e1-construction-20260808/per_project.csv
```

## Inputs

- **Library:** 9,760 portable Injectors over 1,615 target diagnostics, assembled
  from the 622 files the canonical audit checksums (8,235 lexical, 1,525 append).
- **Sources:** 13 projects, clean-gated with the pinned patched Clang at
  `llvmorg-22.1.8`, production-only, zero test/test-support paths.
- **Splits** (frozen before generation, seed 20260808, 15%): train 2,694 TUs
  over 9 projects; `eval_unseen_tu` 440; `heldout_project` 2,263 over 4 projects
  (Abseil, FFmpeg, leveldb, json-c) that contribute no training data at all.

## Result

| ops | split | sources | records | diagnostics | projects | TUs reached | compiles | compiles/record | wall (s) | model calls |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| lexical | train | 2,694 | **5,764** | **401** | 9 | 2,287 | 47,494 | 8.2 | 5,104 | **0** |
| lexical | eval_unseen_tu | 440 | 1,280 | 116 | 9 | 427 | 4,123 | 3.2 | 613 | **0** |
| lexical | heldout_project | 2,263 | **2,325** | **138** | 4 | 987 | 23,465 | 10.1 | 139 | **0** |
| append | train | 2,694 | 1,706 | 72 | 9 | 780 | 57,755 | 33.9 | 6,509 | **0** |
| append | eval_unseen_tu | 440 | 793 | 33 | 9 | 409 | 8,986 | 11.3 | 1,214 | **0** |
| append | heldout_project | 2,263 | 3,229 | 131 | 4 | 1,113 | 14,953 | 4.6 | 150 | **0** |

**Union: 15,097 records, 525 distinct diagnostics (468 in the frozen 1,935
paper scope), 4,194 distinct source translation units, 13 projects, 407
diagnostics at multiplicity ≥ 3.**

Against the plan's release targets: 10,000–30,000 records ✓ (15,097); at least
three projects ✓ (13); 350–400 diagnostics at multiplicity three ✓ (407).
RealSource strict coverage is 468/1,935, below the ~1,000 goal — one capped
replay pass does not exhaust the library.

## Amortization — the reuse claim

| arm | Injectors that produced a record | sources per Injector (mean) | reached >1 source | reached >1 project |
|---|---:|---:|---:|---:|
| lexical / train | 419 | 13.8 | 309 | 150 |
| lexical / heldout_project | 152 | 15.3 | 125 | 18 |
| append / train | 72 | 23.7 | 70 | 32 |

One Injector, authored once, yields ~14 verified records across distinct real
translation units, and 150 of them cross a project boundary.

## Transfer to projects the library has never seen

The `heldout_project` arms are Abseil, FFmpeg, leveldb, and json-c — no training
record comes from any of them. Lexical Injectors produced **2,325 records over
138 diagnostics from 987 translation units in 139 seconds of one node**, with no
model call. That is the cost/reach sentence the paper makes.

## Integrity

All 15,097 records pass the full invariant audit with **zero violations**: no
test or test-support source, `corrected_src` present and different from the
erroneous source, primary typed diagnostic exactly equal to the Injector's
declared target, no opportunistic relabelling, every record's `source_split`
matching the arm it was generated for, and 15,097 distinct record IDs.

## A configuration finding worth keeping

The first run (kept as `lexical-train-cap5-fileorder/`) used a per-shard
diagnostic cap of 5 and the library in archive order. It retained 484 records
over 120 diagnostics — but had actually verified 7,761 records and discarded
7,277 of them, because each of 32 shards spent the full cap independently and
the surplus was trimmed after the merge. Two fixes followed:

1. a **shared, locked per-diagnostic budget** claimed before compiling, so the
   cap is exact and no verified record is produced only to be thrown away;
2. **round-robin ordering by target diagnostic**, so each source's scarce
   verification budget is spent on distinct diagnostics rather than on whichever
   Injectors happen to sit early in the archive.

Same inputs, same node: 484 → 5,764 records and 120 → 401 diagnostics.
