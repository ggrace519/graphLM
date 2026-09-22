"""Tests for graphlm.query — the map queries behind ``graphlm --serve``."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from graphlm import query

# Semantic-find tests that reach ``_run_relevance`` need the real
# ``typesafe_sdk`` types (``Noul``/``NoulCriteria``) even with a fake client
# injected — the fake only substitutes the network call, not the request
# objects. So they skip without the extra, exactly like ``tests/test_evidence.py``
# and the language-pack tests. The gating tests below (no key / empty query)
# short-circuit before that import and run unconditionally.
_HAS_TYPESAFE = importlib.util.find_spec("typesafe_sdk") is not None
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

    def test_dotted_query_does_not_substring_match_data_py(self):
        """'a.py' in 'data.py' must not uniquely resolve (#140)."""
        idx = query.build_index(
            CodebaseGraph(
                directory_tree="",
                import_edges=[_edge("data.py", "z.py")],
                modules=[
                    ModuleDescription(path="data.py", name="data", description="DATA"),
                ],
            )
        )
        match, cands = query.resolve_path(idx, "a.py")
        assert match is None and cands == []

    def test_ambiguous_suffix_returns_only_suffix_candidates(self):
        idx = query.build_index(
            CodebaseGraph(
                directory_tree="",
                import_edges=[_edge("x/foo.py", "y/foo.py"), _edge("z/foobar.py", "y/foo.py")],
            )
        )
        match, cands = query.resolve_path(idx, "foo.py")
        assert match is None and cands == ["x/foo.py", "y/foo.py"]

    def test_absolute_and_repo_prefixed_paths(self, index):
        # An agent holds absolute paths; the map holds repo-relative ones.
        assert query.resolve_path(index, "/home/me/repo/app/core.py") == ("app/core.py", [])
        assert query.resolve_path(index, "repo/app/core.py") == ("app/core.py", [])

    def test_longest_known_path_wins_for_prefixed_query(self):
        idx = query.build_index(
            CodebaseGraph(directory_tree="", import_edges=[_edge("cli.py", "app/cli.py")])
        )
        assert query.resolve_path(idx, "/x/app/cli.py") == ("app/cli.py", [])

    def test_suffix_candidates_are_capped(self):
        edges = [_edge(f"pkg{i}/__init__.py", "core.py") for i in range(30)]
        idx = query.build_index(CodebaseGraph(directory_tree="", import_edges=edges))
        match, cands = query.resolve_path(idx, "__init__.py")
        assert match is None and len(cands) == 20

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

    def test_degree_counts_distinct_files_not_edge_kinds(self):
        g = CodebaseGraph(
            directory_tree="",
            deterministic_edges=[_edge("a.py", "b.py", "import"), _edge("a.py", "b.py", "from")],
            quick_reference=[
                QuickReference(query="q", location="data.py"),
                QuickReference(query="anchored", location="pkg/a.py:main"),
            ],
        )
        idx = query.build_index(g)
        assert query.overview(idx)["most_imported"] == [{"path": "b.py", "imported_by": 1}]
        info = query.module_info(idx, "b.py")
        assert info["imported_by"] == 1
        # neighbors still lists both kinds — that detail is the point of it.
        assert len(query.neighbors(idx, "b.py", "in")["imported_by"]) == 2
        # quick-reference match is path-anchored: `a.py` must not claim data.py.
        assert query.module_info(idx, "a.py")["quick_reference"] == []
        idx2 = query.build_index(
            CodebaseGraph(directory_tree="", import_edges=[_edge("pkg/a.py", "b.py")],
                          quick_reference=g.quick_reference)
        )
        assert query.module_info(idx2, "pkg/a.py")["quick_reference"] == [
            {"query": "anchored", "location": "pkg/a.py:main"}
        ]

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

    def test_find_ignores_question_filler(self, index):
        # "where is" must not make every quick-reference entry a hit.
        hits = query.find(index, "where is the pipeline?")["hits"]
        assert hits and all(h["kind"] != "quick_reference" for h in hits)
        assert hits[0]["kind"] == "symbol"

    def test_find_prefix_matches_inflections(self, index):
        # "redaction" should reach a symbol named _redact_secrets.
        g = CodebaseGraph(
            directory_tree="",
            file_summaries=[
                FileSummary(
                    path="app/scanner.py",
                    summary="Walks the tree.",
                    symbols=[Symbol(name="_redact_secrets", kind="function", description="Masks keys")],
                )
            ],
        )
        hits = query.find(query.build_index(g), "secret redaction")["hits"]
        assert hits[0]["kind"] == "symbol" and hits[0]["name"] == "_redact_secrets"

    def test_find_stopword_only_query_still_searches(self):
        g = CodebaseGraph(
            directory_tree="",
            file_summaries=[FileSummary(path="q.py", summary="", symbols=[
                Symbol(name="find", kind="function", description="Search the map")])],
        )
        hits = query.find(query.build_index(g), "find")["hits"]
        assert hits and hits[0]["name"] == "find"

    def test_limits_are_clamped(self, index):
        assert query.find(index, "app", limit=10_000_000)["hits"]
        d = query.dependents(index, "app/util.py", transitive=True, limit=10_000_000)
        assert d["count"] == 3 and not d["truncated"]
        assert query.dependents(index, "app/util.py", limit=-5)["count"] == 0

    def test_cycles_tiebreak_is_deterministic(self):
        cyc = [
            Cycle(nodes=["z.py", "y.py"], edges=[], length=2, risk_score=1.0),
            Cycle(nodes=["a.py", "b.py"], edges=[], length=2, risk_score=1.0),
        ]
        idx = query.build_index(CodebaseGraph(directory_tree="", import_cycles=cyc))
        assert [c["nodes"] for c in query.cycles(idx)["cycles"]] == [["a.py", "b.py"], ["z.py", "y.py"]]

    def test_find_empty_and_limit(self, index):
        assert query.find(index, "   ") == {"query": "   ", "hits": [], "total": 0}
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


class _RelAns:
    def __init__(self, noul): self.noul = noul


class _RelResp:
    def __init__(self, nouls): self.nouls = nouls


class _RelClient:
    """Fake Jev client: returns a relevance per question from `by_key`."""
    def __init__(self, by_key):
        self.by_key = by_key
        self.calls = 0

    def system_one(self, *, state, questions, timeout=None):
        self.calls += 1
        return _RelResp({k: _RelAns(self.by_key.get(k, 0.1)) for k in questions})


@pytest.mark.skipif(not _HAS_TYPESAFE, reason="needs the typesafe extra for the real Noul types")
class TestSemanticFind:
    def test_ranks_by_relevance(self):
        # The corpus is file_summaries (file-level); c0..cN follow summary order.
        from graphlm.models import CodebaseGraph, FileSummary
        g = CodebaseGraph(directory_tree="t/", file_summaries=[
            FileSummary(path="a.py", summary="alpha"),
            FileSummary(path="b.py", summary="beta"),
            FileSummary(path="c.py", summary="gamma"),
        ])
        by_key = {"c2": 0.97, "c0": 0.05}  # make the LAST candidate most relevant
        res = query.semantic_find(query.build_index(g), "some question",
                                  api_key="k", client=_RelClient(by_key))
        assert res["available"] is True and res["hits"]
        assert res["hits"][0]["relevance"] == 0.97
        assert res["hits"][0]["path"] == "c.py"
        rels = [h["relevance"] for h in res["hits"]]
        assert rels == sorted(rels, reverse=True)

    def test_scores_files_not_directory_modules(self):
        # A large-repo shape: directory modules + file-level summaries. Semantic
        # search must rank FILES (the file-level corpus), not the coarse dirs (#6).
        from graphlm.models import CodebaseGraph, ModuleDescription, FileSummary
        g = CodebaseGraph(
            directory_tree="src/",
            modules=[ModuleDescription(path="src/pkg", name="pkg", description="a package")],
            file_summaries=[
                FileSummary(path="src/pkg/auth.py", summary="login and token handling"),
                FileSummary(path="src/pkg/db.py", summary="database access layer"),
            ],
        )
        res = query.semantic_find(query.build_index(g), "where is login handled?",
                                  api_key="k", client=_RelClient({"c0": 0.95, "c1": 0.1}))
        assert res["hits"][0]["kind"] == "file"
        assert res["hits"][0]["path"] == "src/pkg/auth.py"  # a FILE, not src/pkg

    def test_falls_back_to_modules_without_summaries(self):
        from graphlm.models import CodebaseGraph, ModuleDescription
        g = CodebaseGraph(
            directory_tree="t/",
            modules=[ModuleDescription(path="a.py", name="a", description="alpha"),
                     ModuleDescription(path="b.py", name="b", description="beta")],
        )
        res = query.semantic_find(query.build_index(g), "q", api_key="k",
                                  client=_RelClient({"c0": 0.9, "c1": 0.2}))
        assert res["hits"][0]["kind"] == "module" and res["hits"][0]["path"] == "a.py"

    def test_client_error_signals_unavailable(self, index):
        class _Boom:
            def system_one(self, **k):
                raise RuntimeError("jev down")
        res = query.semantic_find(index, "q", api_key="k", client=_Boom())
        assert res["available"] is False  # caller falls back to find


class TestSemanticFindGating:
    """The unavailable/empty paths short-circuit *before* the SDK import, so
    they run without the typesafe extra (no ``skipif``)."""

    def test_no_key_signals_unavailable(self, index):
        res = query.semantic_find(index, "q", api_key=None, client=_RelClient({}))
        assert res["available"] is False and res["hits"] == []

    def test_empty_query_is_available_empty(self, index):
        res = query.semantic_find(index, "   ", api_key="k", client=_RelClient({}))
        assert res["available"] is True and res["hits"] == []
