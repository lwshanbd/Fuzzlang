"""Tests for NatErr Stage 1 harvest. Uses a tiny synthetic git repo built in
a tmp_path fixture so tests are hermetic + fast."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from real.harvest import (
    FIX_BUILD_RE,
    FixBuildCandidate,
    NatErrProject,
    harvest_metadata,
    write_manifest,
    _hash_email,
)


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=cwd,
                       capture_output=True, text=True, check=True)
    return r.stdout


def _make_repo(path: Path) -> None:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "dev@example.com")
    _git(path, "config", "user.name", "Dev")


def _commit(path: Path, msg: str, *, email: str = "dev@example.com",
            date_iso: str = "2026-01-15T12:00:00Z") -> str:
    (path / "a.c").write_text((path / "a.c").read_text() + "/*edit*/\n"
                              if (path / "a.c").exists() else "int main(){return 0;}\n")
    _git(path, "add", "a.c")
    env = {"GIT_AUTHOR_EMAIL": email, "GIT_COMMITTER_EMAIL": email,
           "GIT_AUTHOR_DATE": date_iso, "GIT_COMMITTER_DATE": date_iso,
           "GIT_AUTHOR_NAME": "T", "GIT_COMMITTER_NAME": "T", "PATH": "/usr/bin"}
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=path, env=env, check=True)
    return _git(path, "rev-parse", "HEAD").strip()


def test_fix_build_regex_matches_expected_variants():
    assert FIX_BUILD_RE.search("fix build: missing header")
    assert FIX_BUILD_RE.search("Fixes build on macOS with LLVM 19")
    assert FIX_BUILD_RE.search("unbreak build after refactor")
    assert FIX_BUILD_RE.search("repair compilation on arm")
    assert FIX_BUILD_RE.search("Fix compile error in foo.cpp")
    assert FIX_BUILD_RE.search("fix ninja build on Windows")
    # Negatives
    assert not FIX_BUILD_RE.search("update README")
    assert not FIX_BUILD_RE.search("refactor parser")
    assert not FIX_BUILD_RE.search("add test coverage")


def test_harvest_picks_up_fix_build_commits_and_skips_others(tmp_path):
    repo = tmp_path / "synth"
    _make_repo(repo)
    # Three commits: noise, fix-build, noise.
    c1 = _commit(repo, "initial checkin", date_iso="2025-07-01T10:00:00Z")
    c2 = _commit(repo, "fix build: missing semicolon in foo.c",
                 date_iso="2025-07-02T10:00:00Z")
    c3 = _commit(repo, "update docs", date_iso="2025-07-03T10:00:00Z")

    proj = NatErrProject(name="synth", git_url="file://local", default_branch="main")
    candidates = harvest_metadata(proj, repo, since_iso_date="2025-06-01")

    # Only c2 should match.
    assert len(candidates) == 1
    c = candidates[0]
    assert c.project == "synth"
    assert c.fix_sha == c2
    assert c.predecessor_sha == c1
    assert "fix build" in c.subject.lower()


def test_harvest_filters_by_date(tmp_path):
    repo = tmp_path / "synth2"
    _make_repo(repo)
    _commit(repo, "fix build: old", date_iso="2025-01-01T10:00:00Z")
    _commit(repo, "fix build: new", date_iso="2025-08-01T10:00:00Z")

    proj = NatErrProject(name="synth2", git_url="file://local", default_branch="main")
    cand = harvest_metadata(proj, repo, since_iso_date="2025-06-01")
    assert len(cand) == 1
    assert "new" in cand[0].subject


def test_harvest_excludes_blocklisted_authors(tmp_path):
    repo = tmp_path / "synth3"
    _make_repo(repo)
    _commit(repo, "fix build: by paper author", email="authors@paper.example")
    _commit(repo, "fix build: by someone else", email="outsider@example.com")

    proj = NatErrProject(name="synth3", git_url="file://local", default_branch="main")
    block = {_hash_email("authors@paper.example")}
    cand = harvest_metadata(
        proj, repo, since_iso_date="2025-06-01",
        author_email_blocklist_hashes=block,
    )
    assert len(cand) == 1
    assert "someone else" in cand[0].subject


def test_harvest_respects_max_candidates(tmp_path):
    repo = tmp_path / "synth4"
    _make_repo(repo)
    for i in range(5):
        _commit(repo, f"fix build #{i}", date_iso=f"2025-0{6+i%4}-01T10:00:00Z")
    proj = NatErrProject(name="synth4", git_url="file://local", default_branch="main")
    cand = harvest_metadata(proj, repo, since_iso_date="2025-06-01", max_candidates=2)
    assert len(cand) == 2


def test_write_manifest_emits_jsonl(tmp_path):
    out = tmp_path / "m.jsonl"
    candidates = [
        FixBuildCandidate(project="x", fix_sha="a" * 40, predecessor_sha="b" * 40,
                          commit_date_iso="2025-06-01T00:00:00Z",
                          subject="fix build", author_email_hash="deadbeef"),
        FixBuildCandidate(project="x", fix_sha="c" * 40, predecessor_sha="d" * 40,
                          commit_date_iso="2025-06-02T00:00:00Z",
                          subject="fix build", author_email_hash="feedface"),
    ]
    write_manifest(candidates, out)
    lines = out.read_text().splitlines()
    assert len(lines) == 2
    import json
    row = json.loads(lines[0])
    assert row["project"] == "x"
    assert row["fix_sha"] == "a" * 40
