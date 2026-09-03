"""Tests for graphlm.query — the map queries behind ``graphlm --serve``."""

from __future__ import annotations

from pathlib import Path

import pytest

from graphlm import query
from graphlm.models import (
    ArchitectureNote,
    CodebaseGraph,
    Cycle,
    EntryPoint,
    FileSummary,
    GraphMeta,
    ImportEdge,
    ModuleDescription,
    QuickReference,
    Symbol,
)
from graphlm.render import write_outputs


def _edge(a: str, b: str, kind: str = "import") -> ImportEdge:
    return ImportEdge(from_path=a, to_path=b, kind=kind)


@pytest.fixture
def graph() -> CodebaseGraph:
    """A small hand-built map with both edge sources, a cycle, and prose sections.

    Shape (AST edges): cli -> core, core -> util, util -> core (cycle),
    tests/test_cli -> cli. The LLM agrees on cli -> core, adds a `uses` edge
    core -> db, and claims util -> models that the parser never saw.
    """
    ast = [
        _edge("app/cli.py", "app/core.py"),
        _edge("app/core.py", "app/util.py", "from"),
        _edge("app/util.py", "app/core.py"),
        _edge("tests/test_cli.py", "app/cli.py", "from"),
    ]
    llm = [
        _edge("./app/cli.py", "app/core.py"),  # same edge, leading ./
        _edge("app/core.py", "app/db.py", "uses"),
        _edge("app/util.py", "app/models.py", "from"),
    ]
    return CodebaseGraph(
        directory_tree="app/",
        import_edges=llm,
        deterministic_edges=ast,
        modules=[
            ModuleDescription(path="app/cli.py", name="CLI", description="Typer entry point"),
            ModuleDescription(path="app/core.py", name="Core", description="Business logic"),
        ],
        file_summaries=[
            FileSummary(
                path="app/core.py",
                summary="Runs the pipeline.",
                symbols=[Symbol(name="run_pipeline", kind="function", description="Runs everything")],
            ),
        ],
        entry_points=[
            EntryPoint(path="app/cli.py", name="main()", kind="cli_command", description="The CLI"),
        ],
        quick_reference=[
            QuickReference(query="where is the CLI entry", location="app/cli.py"),
        ],
        architecture_notes=[ArchitectureNote(note="Two layers.")],
        import_cycles=[
            Cycle(nodes=["app/core.py", "app/util.py"], edges=[], length=2, risk_score=4.2)
        ],
        meta=GraphMeta(created_at="2026-09-02T00:00:00Z", commit_sha="a" * 40),
    )


@pytest.fixture
def index(graph: CodebaseGraph) -> query.MapIndex:
    return query.build_index(graph)


class TestBuildIndex:
    def test_edges_unified_with_source_labels(self, index):
        out = {(r.path, r.kind): r.source for r in index.out_edges["app/cli.py"]}
        assert out == {("app/core.py", "import"): "both"}
        core_out = {(r.path, r.kind): r.source for r in index.out_edges["app/core.py"]}
        assert core_out == {("app/util.py", "from"): "ast", ("app/db.py", "uses"): "llm"}
        util_out = {(r.path, r.kind): r.source for r in index.out_edges["app/util.py"]}
        assert util_out[("app/models.py", "from")] == "llm"

    def test_in_edges_and_cycle_membership(self, index):
        assert [r.path for r in index.in_edges["app/core.py"]] == ["app/cli.py", "app/util.py"]
        assert index.cycle_of["app/core.py"] == [0]
        assert "app/cli.py" not in index.cycle_of

    def test_neighbors_sorted_deterministically(self, graph):
        shuffled = CodebaseGraph(
            directory_tree="",
            import_edges=list(reversed(graph.import_edges)),
            deterministic_edges=list(reversed(graph.deterministic_edges)),
        )
        a = query.build_index(graph)
        b = query.build_index(shuffled)
        assert a.out_edges == b.out_edges and a.in_edges == b.in_edges

    def test_no_ast_edges_is_fine(self):
        idx = query.build_index(CodebaseGraph(directory_tree="", import_edges=[_edge("a.py", "b.py")]))
        assert idx.out_edges["a.py"][0].source == "llm"


class TestResolvePath:
    def test_exact(self, index):
        assert query.resolve_path(index, "app/core.py") == ("app/core.py", [])

    def test_normalises_dot_slash_and_backslash(self, index):
        assert query.resolve_path(index, "./app\\core.py")[0] == "app/core.py"

    def test_unique_suffix(self, index):
        # `cli.py` matches app/cli.py by suffix, not tests/test_cli.py.
        assert query.resolve_path(index, "cli.py") == ("app/cli.py", [])

    def test_ambiguous_substring_returns_candidates(self, index):
        match, cands = query.resolve_path(index, "py")
        assert match is None and len(cands) > 1  # no "/py" suffix; many substring hits
        match, cands = query.resolve_path(index, "core")
        assert match == "app/core.py"  # unique substring

    def test_ambiguous_suffix_returns_only_suffix_candidates(self):
        idx = query.build_index(
            CodebaseGraph(
                directory_tree="",
                import_edges=[_edge("x/foo.py", "y/foo.py"), _edge("z/foobar.py", "y/foo.py")],
            )
        )
        match, cands = query.resolve_path(idx, "foo.py")
        assert match is None and cands == ["x/foo.py", "y/foo.py"]

    def test_unknown(self, index):
        match, cands = query.resolve_path(index, "nope/zzz.py")
        assert match is None and cands == []


class TestQueries:
    def test_overview(self, index):
        ov = query.overview(index)
        assert ov["counts"]["ast_import_edges"] == 4
        assert ov["counts"]["llm_import_edges"] == 3
        assert ov["counts"]["import_cycles"] == 1
        assert ov["most_imported"][0] == {"path": "app/core.py", "imported_by": 2}
        assert ov["entry_points"] == [{"path": "app/cli.py", "name": "main()", "kind": "cli_command"}]
        assert ov["architecture_notes"] == ["Two layers."]
        assert ov["meta"]["commit_sha"] == "a" * 40

    def test_overview_without_meta_or_ast(self):
        ov = query.overview(query.build_index(CodebaseGraph(directory_tree="")))
        assert ov["meta"] is None and ov["counts"]["ast_import_edges"] is None

    def test_module_info(self, index):
        info = query.module_info(index, "core.py")
        assert info["found"] and info["path"] == "app/core.py"
        assert info["module"]["name"] == "Core"
        assert info["summary"] == "Runs the pipeline."
        assert info["symbols"][0]["name"] == "run_pipeline"
        assert info["imports"] == 2 and info["imported_by"] == 2
        assert info["in_cycles"] == [0]
        assert info["entry_points"] == []

    def test_module_info_unknown(self, index):
        info = query.module_info(index, "ghost.py")
        assert info == {"path": "ghost.py", "found": False, "candidates": [], "hint": "no such path in the map"}

    def test_neighbors_both(self, index):
        n = query.neighbors(index, "app/core.py")
        assert n["imports"] == [
            {"path": "app/db.py", "kind": "uses", "source": "llm"},
            {"path": "app/util.py", "kind": "from", "source": "ast"},
        ]
        assert n["imported_by"] == [
            {"path": "app/cli.py", "kind": "import", "source": "both"},
            {"path": "app/util.py", "kind": "import", "source": "ast"},
        ]

    def test_neighbors_direction(self, index):
        assert "imported_by" not in query.neighbors(index, "app/core.py", "out")
        assert "imports" not in query.neighbors(index, "app/core.py", "in")
        with pytest.raises(ValueError):
            query.neighbors(index, "app/core.py", "sideways")

    def test_neighbors_ambiguous(self, index):
        n = query.neighbors(index, "zzz")
        assert n["found"] is False

    def test_dependents_direct(self, index):
        d = query.dependents(index, "app/core.py")
        assert [x["path"] for x in d["dependents"]] == ["app/cli.py", "app/util.py"]
        assert all(x["distance"] == 1 for x in d["dependents"])
        assert d["transitive"] is False and d["truncated"] is False

    def test_dependents_transitive_terminates_on_cycle(self, index):
        d = query.dependents(index, "app/util.py", transitive=True)
        paths = {x["path"]: x["distance"] for x in d["dependents"]}
        # util <- core <- cli <- tests/test_cli ; util <- core <- util is the cycle (skipped)
        assert paths == {"app/core.py": 1, "app/cli.py": 2, "tests/test_cli.py": 3}

    def test_dependents_limit(self, index):
        d = query.dependents(index, "app/util.py", transitive=True, limit=1)
        assert d["count"] == 1 and d["truncated"] is True

    def test_find_ranks_quick_reference_first(self, index):
        hits = query.find(index, "cli entry")["hits"]
        assert hits[0]["kind"] == "quick_reference"
        kinds = {h["kind"] for h in hits}
        assert {"quick_reference", "module", "entry_point"} <= kinds

    def test_find_symbol_and_summary(self, index):
        hits = query.find(index, "pipeline")["hits"]
        assert {h["kind"] for h in hits} == {"symbol", "file_summary"}
        assert hits[0]["kind"] == "symbol"

    def test_find_empty_and_limit(self, index):
        assert query.find(index, "   ") == {"query": "   ", "hits": []}
        r = query.find(index, "app", limit=1)
        assert len(r["hits"]) == 1 and r["total"] > 1

    def test_cycles(self, index):
        c = query.cycles(index)
        assert c["count"] == 1
        assert c["cycles"][0] == {"nodes": ["app/core.py", "app/util.py"], "length": 2, "risk_score": 4.2}

    def test_entry_points(self, index):
        assert query.entry_points(index)["entry_points"][0]["name"] == "main()"


class TestStaleness:
    def test_fresh(self, index, monkeypatch):
        monkeypatch.setattr("graphlm.provenance.git_commit_sha", lambda p: "a" * 40)
        s = query.staleness(index, Path("."))
        assert s["state"] == "fresh" and s["hint"] is None

    def test_stale(self, index, monkeypatch):
        monkeypatch.setattr("graphlm.provenance.git_commit_sha", lambda p: "b" * 40)
        s = query.staleness(index, Path("."))
        assert s["state"] == "stale" and "graphlm ." in s["hint"]

    def test_unknown_when_no_git(self, index, monkeypatch):
        monkeypatch.setattr("graphlm.provenance.git_commit_sha", lambda p: None)
        assert query.staleness(index, Path("."))["state"] == "unknown"

    def test_unknown_when_no_meta(self, monkeypatch):
        monkeypatch.setattr("graphlm.provenance.git_commit_sha", lambda p: "a" * 40)
        idx = query.build_index(CodebaseGraph(directory_tree=""))
        s = query.staleness(idx, Path("."))
        assert s["state"] == "unknown" and s["generated_at"] is None


class TestLoadMap:
    def test_round_trips_written_graph(self, graph, tmp_path):
        write_outputs(graph, tmp_path, html=False, diff=False)
        loaded = query.load_map(tmp_path / "GRAPH.json")
        assert len(loaded.deterministic_edges) == 4
        assert loaded.meta.commit_sha == "a" * 40

    def test_missing_raises(self, tmp_path):
        with pytest.raises(query.MapUnavailable, match="run `graphlm .`"):
            query.load_map(tmp_path / "GRAPH.json")

    def test_corrupt_raises(self, tmp_path):
        (tmp_path / "GRAPH.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(query.MapUnavailable, match="could not be read"):
            query.load_map(tmp_path / "GRAPH.json")
