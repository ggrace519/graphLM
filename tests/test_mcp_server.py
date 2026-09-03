"""Tests for the MCP transport (``graphlm --serve``).

Drives the real server through the SDK's in-memory client — no subprocess,
no stdio — so the registered tools, their schemas, and the error path are
exercised end to end. Skipped when the ``mcp`` extra is not installed; the
query logic itself is covered by ``test_query.py`` without it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

mcp = pytest.importorskip("mcp")

import anyio  # noqa: E402  (after importorskip — anyio ships with mcp)
from mcp.client import Client  # noqa: E402

from graphlm import mcp_server  # noqa: E402
from graphlm.models import (  # noqa: E402
    CodebaseGraph,
    Cycle,
    EntryPoint,
    GraphMeta,
    ImportEdge,
    ModuleDescription,
    QuickReference,
)
from graphlm.render import write_outputs  # noqa: E402


def _graph(sha: str = "a" * 40) -> CodebaseGraph:
    return CodebaseGraph(
        directory_tree="app/",
        import_edges=[ImportEdge(from_path="app/cli.py", to_path="app/core.py", kind="import")],
        deterministic_edges=[
            ImportEdge(from_path="app/cli.py", to_path="app/core.py", kind="import"),
            ImportEdge(from_path="app/core.py", to_path="app/util.py", kind="from"),
            ImportEdge(from_path="app/util.py", to_path="app/core.py", kind="import"),
        ],
        modules=[ModuleDescription(path="app/core.py", name="Core", description="Business logic")],
        entry_points=[EntryPoint(path="app/cli.py", name="main()", kind="cli_command", description="CLI")],
        quick_reference=[QuickReference(query="where is the CLI entry", location="app/cli.py")],
        import_cycles=[Cycle(nodes=["app/core.py", "app/util.py"], edges=[], length=2, risk_score=3.0)],
        meta=GraphMeta(created_at="2026-09-02T00:00:00Z", commit_sha=sha),
    )


@pytest.fixture
def map_dir(tmp_path: Path) -> Path:
    out = tmp_path / ".graphlm"
    write_outputs(_graph(), out, html=False, diff=False)
    return out


def _call(server, name: str, args: dict | None = None) -> dict:
    """Call one tool through the in-memory client and return its structured payload."""

    async def go():
        async with Client(server) as client:
            return await client.call_tool(name, args or {})

    result = anyio.run(go)
    if result.is_error:
        return {"__error__": "".join(getattr(c, "text", "") for c in result.content)}
    if result.structured_content is not None:
        return result.structured_content
    return json.loads("".join(getattr(c, "text", "") for c in result.content))


def _tool_names(server) -> list[str]:
    async def go():
        async with Client(server) as client:
            return [t.name for t in (await client.list_tools()).tools]

    return anyio.run(go)


class TestServer:
    def test_registers_every_map_tool(self, tmp_path, map_dir):
        server = mcp_server.build_server(tmp_path, map_dir / "GRAPH.json")
        assert _tool_names(server) == [
            "overview", "module", "neighbors", "dependents", "find",
            "cycles", "entry_points", "staleness",
        ]

    def test_overview_and_neighbors(self, tmp_path, map_dir):
        server = mcp_server.build_server(tmp_path, map_dir / "GRAPH.json")
        ov = _call(server, "overview")
        assert ov["counts"]["ast_import_edges"] == 3
        assert ov["most_imported"][0]["path"] == "app/core.py"
        n = _call(server, "neighbors", {"path": "core.py", "direction": "in"})
        assert n["found"] and [r["path"] for r in n["imported_by"]] == ["app/cli.py", "app/util.py"]
        assert n["imported_by"][0]["source"] == "both"

    def test_find_module_dependents_cycles_entry_points(self, tmp_path, map_dir):
        server = mcp_server.build_server(tmp_path, map_dir / "GRAPH.json")
        assert _call(server, "find", {"query_text": "cli entry"})["hits"][0]["kind"] == "quick_reference"
        assert _call(server, "module", {"path": "app/core.py"})["module"]["name"] == "Core"
        d = _call(server, "dependents", {"path": "app/util.py", "transitive": True})
        assert {x["path"] for x in d["dependents"]} == {"app/core.py", "app/cli.py"}
        assert _call(server, "cycles")["count"] == 1
        assert _call(server, "entry_points")["entry_points"][0]["name"] == "main()"

    def test_staleness_uses_project_dir(self, tmp_path, map_dir, monkeypatch):
        seen: list[Path] = []

        def fake_sha(p):
            seen.append(Path(p))
            return "a" * 40

        monkeypatch.setattr("graphlm.provenance.git_commit_sha", fake_sha)
        server = mcp_server.build_server(tmp_path, map_dir / "GRAPH.json")
        assert _call(server, "staleness")["state"] == "fresh"
        assert seen == [tmp_path]

    def test_missing_map_is_a_tool_error_not_a_crash(self, tmp_path):
        server = mcp_server.build_server(tmp_path, tmp_path / "GRAPH.json")
        err = _call(server, "overview")["__error__"]
        assert "run `graphlm .`" in err
        # The server survives: a later call still works once the map appears.
        write_outputs(_graph(), tmp_path, html=False, diff=False)
        assert _call(server, "overview")["counts"]["modules"] == 1

    def test_corrupt_map_is_a_tool_error(self, tmp_path):
        (tmp_path / "GRAPH.json").write_text("{nope", encoding="utf-8")
        server = mcp_server.build_server(tmp_path, tmp_path / "GRAPH.json")
        assert "could not be read" in _call(server, "overview")["__error__"]

    def test_reloads_when_map_changes_on_disk(self, tmp_path, map_dir):
        json_path = map_dir / "GRAPH.json"
        server = mcp_server.build_server(tmp_path, json_path)
        assert _call(server, "overview")["meta"]["commit_sha"] == "a" * 40
        write_outputs(_graph(sha="b" * 40), map_dir, html=False, diff=False)
        # Force a distinct mtime even on coarse filesystems.
        st = json_path.stat()
        os.utime(json_path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
        assert _call(server, "overview")["meta"]["commit_sha"] == "b" * 40


class TestMapCache:
    def test_caches_until_mtime_changes(self, tmp_path, map_dir, monkeypatch):
        cache = mcp_server.MapCache(map_dir / "GRAPH.json")
        first = cache.index()
        assert cache.index() is first  # same object: no reload
        loads = []
        monkeypatch.setattr(mcp_server, "load_map", lambda p: loads.append(p) or _graph())
        st = cache.json_path.stat()
        os.utime(cache.json_path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
        assert cache.index() is not first and loads == [cache.json_path]

    def test_missing_file_resets_and_raises(self, tmp_path):
        cache = mcp_server.MapCache(tmp_path / "GRAPH.json")
        with pytest.raises(mcp_server.MapUnavailable):
            cache.index()
