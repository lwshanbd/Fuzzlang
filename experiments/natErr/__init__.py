"""NatErr: natural compilation-error harvest from real C/C++ projects.

See refine-logs/FINAL_PROPOSAL.md NatErr Pipeline section.

Two stages:
  1. `harvest_metadata`  — git-log scan for fix-build commits on each project.
     Records (project, fix_sha, predecessor_sha, commit_date, commit_msg) per
     candidate instance. Fast, no build. Output: manifest_raw.jsonl.
  2. `reproduce_compile` — per-project build driver. For each predecessor SHA,
     checks out, attempts compile, records the primary diagnostic if it fails.
     Slow, CPU-heavy. Output: manifest.jsonl (only reproducible errors).

Stage 1 is portable (pure git, no compile). Stage 2 is per-project: each
project has its own build system (make / ninja / cmake / bazel / meson /
autotools) so a build driver lives in natErr/drivers/.
"""
from experiments.natErr.harvest import (
    FixBuildCandidate,
    NatErrProject,
    harvest_metadata,
)

__all__ = ["FixBuildCandidate", "NatErrProject", "harvest_metadata"]
