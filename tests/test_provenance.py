"""Tests for provenance capture (git SHA, timestamp, version)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from graphlm.provenance import git_commit_sha, graphlm_version, now_utc_iso


def _init_repo_with_commit(path: Path) -> str:
    """Create a git repo with one commit at `path`, return its full SHA."""
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(
        ["git", "-C", str(path), "-c", "user.email=t@t", "-c", "user.name=t",
         "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m",
         "init"],
        check=True,
    )
    out = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    )
    return out.stdout.strip()


class TestGitCommitSha:
    def test_real_repo_returns_head_sha(self, tmp_path: Path):
        expected = _init_repo_with_commit(tmp_path)
        got = git_commit_sha(tmp_path)
        assert got == expected
        assert re.fullmatch(r"[0-9a-f]{40}", got)

    def test_non_git_dir_returns_none(self, tmp_path: Path):
        # A bare directory with no repo anywhere above it (tmp_path is not a repo).
        assert git_commit_sha(tmp_path) is None

    def test_empty_repo_returns_none(self, tmp_path: Path):
        # `git init` with no commits: `git rev-parse HEAD` exits non-zero and
        # prints the literal "HEAD" to stdout. Must NOT be stamped as a SHA.
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        assert git_commit_sha(tmp_path) is None

    def test_subdirectory_returns_parent_repo_head(self, tmp_path: Path):
        # Pointing at a subdir of a repo resolves the containing repo's HEAD —
        # git's own behavior, and the correct staleness anchor for that subtree.
        expected = _init_repo_with_commit(tmp_path)
        sub = tmp_path / "pkg" / "inner"
        sub.mkdir(parents=True)
        assert git_commit_sha(sub) == expected

    def test_git_not_installed_returns_none(self, tmp_path: Path, monkeypatch):
        # Simulate git missing from PATH: subprocess raises FileNotFoundError,
        # which must be swallowed to None, not propagated.
        def _boom(*a, **k):
            raise FileNotFoundError("git")

        monkeypatch.setattr(subprocess, "run", _boom)
        assert git_commit_sha(tmp_path) is None

    def test_never_raises_on_odd_output(self, tmp_path: Path, monkeypatch):
        # A zero-exit git that returns junk (not a hash) must yield None.
        class _Proc:
            returncode = 0
            stdout = "not-a-sha\n"

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc())
        assert git_commit_sha(tmp_path) is None

    def test_accepts_sha256_hash(self, tmp_path: Path, monkeypatch):
        # SHA-256 object-format repos produce 64-hex commit ids; accept them.
        sha256 = "a" * 64

        class _Proc:
            returncode = 0
            stdout = sha256 + "\n"

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc())
        assert git_commit_sha(tmp_path) == sha256


class TestNowUtcIso:
    def test_shape(self):
        ts = now_utc_iso()
        # e.g. 2026-08-30T14:22:05Z — ISO 8601, UTC, second precision, Z suffix.
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", ts)


class TestGraphlmVersion:
    def test_returns_str_or_none(self):
        # Installed in the test venv -> a version string; never raises.
        v = graphlm_version()
        assert v is None or isinstance(v, str)

    def test_returns_none_when_metadata_missing(self, monkeypatch):
        # A source checkout with no installed dist metadata -> None, not a raise.
        import importlib.metadata as md

        def _boom(_name):
            raise md.PackageNotFoundError("graphlm")

        monkeypatch.setattr(md, "version", _boom)
        assert graphlm_version() is None
