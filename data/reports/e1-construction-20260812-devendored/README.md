# E1 — Construction reach and cost, recomputed without vendored source, 2026-08-12

**This supersedes [e1-construction-20260808](../e1-construction-20260808/README.md)
for every per-project and headline count.** That report attributed fetched
dependencies to the project that fetched them: duckdb and protobuf vendor
Abseil and others under `build/_deps/`, and the clean-source gate of the time
rejected test paths but not vendored ones. `is_vendored_path()` now rejects
`_deps/`, `third_party/`, `vendor/`, `contrib/`, `deps/`, `CMakeFiles/`, and
generated unity-build stubs; this is the same run recounted under that rule.

Reproduce — identical to the 08-08 command with one flag added:

```
PYTHONPATH=src python3 src/gen/fuzzlang_dsl/run_e1_construction_report.py \
  --run-dir data/gen/experiments/e1-library-replay-v0001 \
  --canonical-map data/reports/strict-injector-coverage-20260807-canonical/diagnostic_record_map.csv \
  --exclude-vendored \
  --report-out data/gen/experiments/e1-library-replay-v0001/e1-construction-report-devendored.json \
  --table-out data/reports/e1-construction-20260812-devendored/arm_table.csv \
  --per-project-out data/reports/e1-construction-20260812-devendored/per_project.csv
```

## What changed

| metric | published 08-08 | recomputed | delta |
|---|---:|---:|---:|
| records | 15,097 | **13,007** | −2,090 (−13.8%) |
| distinct diagnostics | 525 | **514** | −11 |
| in the 1,935 paper scope | 468 | **459** | −9 |
| source translation units | 4,194 | **3,714** | −480 |
| projects | 13 | **13** | 0 |
| diagnostics at multiplicity ≥ 3 | 407 | **395** | −12 |
| Injectors that produced a record | 632 | **610** | −22 |

**Every release target still holds:** 10,000–30,000 records ✓ (13,007), at
least three projects ✓ (13), 350–400 diagnostics at multiplicity three ✓ (395).
No project drops out of the corpus, and no held-out project is affected at all
— Abseil, FFmpeg, leveldb, and json-c vendor nothing, so both `heldout_project`
arms are unchanged (2,325 and 3,229 records).

## Per-arm table

| ops | split | records | diagnostics | projects | TUs | vendored dropped | injectors | sources/injector | cross-project injectors |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| lexical | train | 4,633 | 382 | 9 | 1,878 | 1,131 | 395 | 11.7 | 110 |
| lexical | eval_unseen_tu | 1,088 | 107 | 9 | 363 | 192 | 107 | 10.2 | 52 |
| lexical | heldout_project | 2,325 | 138 | 4 | 987 | 0 | 152 | 15.3 | 18 |
| append | train | 1,109 | 66 | 9 | 550 | 597 | 66 | 16.8 | 23 |
| append | eval_unseen_tu | 623 | 33 | 9 | 346 | 170 | 33 | 18.9 | 14 |
| append | heldout_project | 3,229 | 131 | 4 | 1,113 | 0 | 131 | 24.6 | 10 |

Model calls remain **0** and GPU hours remain **0** in every arm; the filter
removes records, never cost.

## Which projects were overstated

| ops | split | project | published | recomputed | dropped |
|---|---|---|---:|---:|---:|
| lexical | train | duckdb | 961 | **102** | 859 |
| lexical | train | protobuf | 777 | **508** | 269 |
| append | train | duckdb | 628 | **35** | 593 |
| lexical | eval_unseen_tu | duckdb | 177 | **15** | 162 |
| append | eval_unseen_tu | duckdb | 175 | **15** | 160 |
| lexical | eval_unseen_tu | protobuf | 146 | **119** | 27 |
| append | eval_unseen_tu | protobuf | 67 | **58** | 9 |
| append | train | protobuf | 209 | **206** | 3 |
| lexical/append | * | yaml-cpp | 91 | **83** | 8 |

Across all six arms only three projects move at all:

| project | published | recomputed | dropped |
|---|---:|---:|---:|
| duckdb | 1,941 | **167** | 1,774 |
| protobuf | 1,199 | **891** | 308 |
| yaml-cpp | 91 | **83** | 8 |

duckdb is the extreme case: **91% of its records came from vendored source**,
and its lexical-train diagnostic count falls from 81 to 24. Its remaining 167
records are genuine duckdb source. The other ten projects — curl, ffmpeg, fmt,
json-c, leveldb, libuv, llvm, spdlog, zlib, abseil — are untouched.

## Effect on the amortization claim

The reuse sentence weakens slightly but survives: mean sources per Injector
falls from 23.9 to 21.3 pooled, and on the lexical/train arm from 13.8 to 11.7.
Cross-project reach is *better* characterised now, because an Injector that
"reached duckdb and protobuf" via each project's copy of Abseil was reaching
one codebase twice. 110 lexical/train Injectors still cross a genuine project
boundary.

## Effect on E3

E3's training arms drew from this pool, so 31 FuzzLang and 26 Mechanical
training records were vendored Abseil while Abseil was a held-out evaluation
project. That contamination is documented in
[e3-sft-value-20260811](../e3-sft-value-20260811/README.md); its `excl. Abseil`
column is the trustworthy unseen-project number. Retraining under the filter is
not required for E3's conclusion — the contaminated arms are the ones that
*lose* on Abseil — but any future arm must be built from a de-vendored pool.

## Files

- `arm_table.csv` — the per-arm table above.
- `per_project.csv` — recomputed per-project records, diagnostics, and TUs.
- `../../gen/experiments/e1-library-replay-v0001/e1-construction-report-devendored.json`
  — full report with input paths.
