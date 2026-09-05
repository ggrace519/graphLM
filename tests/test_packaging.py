"""Release artifact invariants."""

from __future__ import annotations

import shutil
import subprocess
import tarfile
import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_version_bump_cannot_commit_or_create_the_publish_tag() -> None:
    """A release must pass PR/main CI before a maintainer creates its tag."""
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as pyproject_file:
        bump_config = tomllib.load(pyproject_file)["tool"]["bumpversion"]

    assert bump_config["commit"] is False
    assert bump_config["tag"] is False


def test_sdist_excludes_claude_workspace_metadata(tmp_path: Path) -> None:
    """Workspace-agent state must never enter the public source archive."""
    project_copy = tmp_path / "project"
    project_copy.mkdir()
    for filename in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copy2(PROJECT_ROOT / filename, project_copy / filename)
    shutil.copytree(
        PROJECT_ROOT / "graphlm",
        project_copy / "graphlm",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    marker = project_copy / ".claude" / "packaging-sentinel.txt"
    marker.parent.mkdir()
    marker.write_text("must not ship\n", encoding="utf-8")

    dist_dir = tmp_path / "dist"
    subprocess.run(
        ["uv", "build", "--sdist", "--out-dir", str(dist_dir)],
        cwd=project_copy,
        check=True,
        capture_output=True,
        text=True,
    )

    archive = next(dist_dir.glob("*.tar.gz"))
    with tarfile.open(archive, "r:gz") as source_dist:
        archived_paths = source_dist.getnames()

    assert not any("/.claude/" in path for path in archived_paths)
