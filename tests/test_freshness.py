"""Tests for fresh-run cleanup + version detection (``graphlm.freshness``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from graphlm.freshness import (
    STATE_FILENAME,
    graphlm_artifact_names,
    keep_names,
    prior_version,
    remove_stale_artifacts,
    version_changed,
)
from graphlm.models import CodebaseGraph, GraphMeta


# --- artifact-name derivation ------------------------------------------------


def test_artifact_names_default_suffix():
    names = graphlm_artifact_names(
        md_suffix="GRAPH",
        json_suffix="GRAPH",
        html_suffix="GRAPH",
        diff_suffix="GRAPH",
    )
    assert names == {
        "GRAPH.md",
        "GRAPH.json",
        "GRAPH.html",
        "GRAPH_DIFF.md",
        "GRAPH_DIFF.json",
        STATE_FILENAME,
    }


def test_artifact_names_track_custom_suffix():
    # A library caller writing map.json → map.* names are cleaned, not GRAPH.*.
    names = graphlm_artifact_names(
        md_suffix="map", json_suffix="map", html_suffix="map", diff_suffix="map"
    )
    assert "map.json" in names and "map_DIFF.json" in names
    assert "GRAPH.json" not in names


def test_keep_names_json_off():
    keep = keep_names(
        md_suffix="GRAPH",
        json_suffix="GRAPH",
        html_suffix="GRAPH",
        diff_suffix="GRAPH",
        json=False,
        html=True,
        diff=True,
    )
    assert "GRAPH.md" in keep and STATE_FILENAME in keep
    assert "GRAPH.html" in keep and "GRAPH_DIFF.md" in keep
    # No JSON deliverable when json=False.
    assert "GRAPH.json" not in keep and "GRAPH_DIFF.json" not in keep


# --- version detection -------------------------------------------------------


def _graph_v(version):
    return CodebaseGraph(
        directory_tree="root/",
        meta=GraphMeta(created_at="t", graphlm_version=version),
    )


def test_prior_version_reads_meta():
    assert prior_version(_graph_v("0.5.0")) == "0.5.0"
    assert prior_version(_graph_v(None)) is None
    assert prior_version(None) is None
    assert prior_version(CodebaseGraph(directory_tree="root/")) is None  # no meta


@pytest.mark.parametrize(
    "old,new,changed",
    [
        ("0.5.0", "0.6.0", True),
        ("0.6.0", "0.6.0", False),
        (None, "0.6.0", True),  # meta-less prior counts as different
        ("0.6.0", None, False),  # unknown current → never claim a change
        (None, None, False),
    ],
)
def test_version_changed(old, new, changed):
    assert version_changed(old, new) is changed


# --- cleanup safety ----------------------------------------------------------


def test_removes_stale_but_keeps_requested(tmp_path):
    for name in ("GRAPH.md", "GRAPH.json", "GRAPH.html"):
        (tmp_path / name).write_text("x")
    names = graphlm_artifact_names(
        md_suffix="GRAPH", json_suffix="GRAPH", html_suffix="GRAPH", diff_suffix="GRAPH"
    )
    removed = remove_stale_artifacts(tmp_path, names, keep={"GRAPH.md"})
    assert "GRAPH.json" in removed and "GRAPH.html" in removed
    assert not (tmp_path / "GRAPH.json").exists()
    assert (tmp_path / "GRAPH.md").exists()  # kept


def test_user_lookalikes_survive(tmp_path):
    # The exact-name allowlist must never touch a user's near-miss files.
    survivors = ["GRAPH_notes.md", "GRAPHICS.md", "graph.json", "notes.txt"]
    for name in survivors:
        (tmp_path / name).write_text("mine")
    names = graphlm_artifact_names(
        md_suffix="GRAPH", json_suffix="GRAPH", html_suffix="GRAPH", diff_suffix="GRAPH"
    )
    remove_stale_artifacts(tmp_path, names, keep=set())
    for name in survivors:
        assert (tmp_path / name).exists(), f"{name} must not be deleted"


def test_symlinked_artifact_is_skipped(tmp_path):
    target = tmp_path / "real.json"
    target.write_text("canary")
    link = tmp_path / "GRAPH.json"
    link.symlink_to(target)
    names = graphlm_artifact_names(
        md_suffix="GRAPH", json_suffix="GRAPH", html_suffix="GRAPH", diff_suffix="GRAPH"
    )
    removed = remove_stale_artifacts(tmp_path, names, keep=set())
    assert "GRAPH.json" not in removed
    assert link.is_symlink()  # left in place
    assert target.read_text() == "canary"  # target untouched


def test_unlink_failure_never_raises(tmp_path, monkeypatch):
    (tmp_path / "GRAPH.json").write_text("x")
    names = graphlm_artifact_names(
        md_suffix="GRAPH", json_suffix="GRAPH", html_suffix="GRAPH", diff_suffix="GRAPH"
    )

    def boom(self):
        raise OSError("disk on fire")

    monkeypatch.setattr(Path, "unlink", boom)
    # Must not raise — cleanup runs after the paid LLM call.
    removed = remove_stale_artifacts(tmp_path, names, keep=set())
    assert removed == []
