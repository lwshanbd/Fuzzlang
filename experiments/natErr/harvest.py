"""Stage 1 NatErr: git-log harvest of fix-build candidate commits.

For each project, scan commits whose message matches the fix-build regex AND
whose commit date is on or after the calendar cutoff. Record (fix_sha,
predecessor_sha) pairs; the predecessor is the candidate broken state.

No compile attempt here — this stage is pure git metadata, runs fast (a few
minutes per project), and is safe to run anywhere (even on the Polaris login
node at -j4; the actual build/reproduction must run elsewhere).
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


FIX_BUILD_RE = re.compile(
    r"(?i)"
    # intent verb
    r"\b(?:fix(?:ing|es|ed)?|repair(?:s|ed)?|unbreak(?:s|ed)?)\b"
    # some gap, non-greedy, bounded
    r".{0,120}?"
    # subject noun. `compil\w*` catches compile / compilation / compiler etc.
    # without requiring a word boundary immediately after `compil`.
    r"\b(?:build|compil\w*|cmake|ninja|linker|link(?:[- ]error)?|"
    r"undefined[- ]reference)\b"
)


@dataclass(frozen=True)
class NatErrProject:
    """Declaration of one NatErr source project."""

    name: str                           # short name, used as manifest key.
    git_url: str                        # https clone URL.
    default_branch: str                 # usually "main" or "master".


@dataclass(frozen=True)
class FixBuildCandidate:
    """One fix-build commit + the predecessor that was (presumably) broken."""

    project: str
    fix_sha: str
    predecessor_sha: str
    commit_date_iso: str                # ISO 8601, UTC.
    subject: str                        # first line of commit message.
    author_email_hash: str              # sha256 of author email, to honor anonymity
                                        # during the authors-must-not-be-in-harvest filter.


def _run_git(args: list[str], cwd: Path) -> str:
    r = subprocess.run(["git", *args], cwd=cwd,
                       capture_output=True, text=True, check=True,
                       timeout=300.0)
    return r.stdout


def _hash_email(email: str) -> str:
    import hashlib
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()[:16]


def harvest_metadata(
    project: NatErrProject,
    repo_dir: Path,
    *,
    since_iso_date: str,
    author_email_blocklist_hashes: set[str] | None = None,
    max_candidates: int | None = None,
) -> list[FixBuildCandidate]:
    """Scan `repo_dir` (an already-cloned checkout of `project`) for fix-build
    commits on or after `since_iso_date`. Returns (possibly empty) list.

    `author_email_blocklist_hashes` filters out commits authored by anyone
    whose sha256(email) is in the set — used to exclude this paper's authors
    from the eval split per the NatErr purity rule.
    """
    blocklist = author_email_blocklist_hashes or set()

    # Use `--grep` for a server-side filter, then refine with Python regex
    # (git's grep is BRE, not PCRE, so our richer regex runs client-side).
    log_format = "%H%x09%P%x09%aI%x09%ae%x09%s"  # sha \t parents \t author_iso \t email \t subject
    # Client-side does all filtering:
    #   - `git --since` is lenient about boundary dates and timezones (a date
    #     ON the cutoff day can be excluded unpredictably), so we compare
    #     ISO 8601 strings lexicographically in Python instead.
    #   - git's `--grep` uses POSIX BRE, not PCRE, so our richer regex must
    #     also run client-side.
    log = _run_git(
        ["log",
         f"--pretty=format:{log_format}",
         "--first-parent",             # only mainline commits
         project.default_branch],
        cwd=repo_dir,
    )

    candidates: list[FixBuildCandidate] = []
    for line in log.splitlines():
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        sha, parents, date_iso, email, subject = parts[:5]

        # Client-side date filter: lexicographic ISO 8601 comparison.
        # date_iso is author date in `%aI` format (e.g. 2025-06-01T10:00:00Z).
        if date_iso < since_iso_date:
            continue

        if not FIX_BUILD_RE.search(subject):
            continue

        email_hash = _hash_email(email)
        if email_hash in blocklist:
            continue

        # Pick the first parent as the predecessor. For merge commits, this is
        # the tip of the target branch before the merge; for regular commits,
        # it's the previous HEAD. Both are reasonable "was broken" candidates.
        parent_list = parents.split()
        if not parent_list:
            continue
        predecessor = parent_list[0]

        candidates.append(FixBuildCandidate(
            project=project.name,
            fix_sha=sha,
            predecessor_sha=predecessor,
            commit_date_iso=date_iso,
            subject=subject[:200],       # cap to keep manifest compact.
            author_email_hash=email_hash,
        ))

        if max_candidates is not None and len(candidates) >= max_candidates:
            break

    return candidates


def write_manifest(candidates: list[FixBuildCandidate], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        for c in candidates:
            f.write(json.dumps(asdict(c), sort_keys=True) + "\n")


# ---- Default project list (keep in sync with FINAL_PROPOSAL.md NatErr sources) ----

NATERR_DEFAULT_PROJECTS: list[NatErrProject] = [
    NatErrProject("llvm", "https://github.com/llvm/llvm-project.git", "main"),
    NatErrProject("chromium",
                  "https://chromium.googlesource.com/chromium/src.git", "main"),
    NatErrProject("ffmpeg", "https://git.ffmpeg.org/ffmpeg.git", "master"),
    NatErrProject("libreoffice",
                  "https://git.libreoffice.org/core", "master"),
    NatErrProject("postgresql",
                  "https://git.postgresql.org/git/postgresql.git", "master"),
    NatErrProject("blender",
                  "https://projects.blender.org/blender/blender.git", "main"),
    NatErrProject("qt", "https://code.qt.io/qt/qtbase.git", "dev"),
    NatErrProject("bitcoin",
                  "https://github.com/bitcoin/bitcoin.git", "master"),
]

NATERR_DEFAULT_SINCE = "2025-06-01"   # see FINAL_PROPOSAL.md calendar-cut rule.
