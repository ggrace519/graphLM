"""Tests for import fan-in (blast radius) computation (``graphlm.degree``)."""

from __future__ import annotations

from graphlm.degree import fan_in, top_fan_in
from graphlm.models import CodebaseGraph, ImportEdge


def _edge(a: str, b: str, kind: str = "import") -> ImportEdge:
    return ImportEdge(from_path=a, to_path=b, kind=kind)


def test_empty_graph_has_no_fan_in():
    g = CodebaseGraph(directory_tree="root/")
    assert fan_in(g) == {}
    assert top_fan_in(g) == []


def test_counts_distinct_importers_not_edge_rows():
    # a.py imports x.py twice (import + from-import); counts as ONE importer.
    g = CodebaseGraph(
        directory_tree="root/",
        import_edges=[
            _edge("a.py", "x.py", "import"),
            _edge("a.py", "x.py", "from"),
            _edge("b.py", "x.py"),
        ],
    )
    assert fan_in(g)["x.py"] == 2  # a.py and b.py, not 3 rows


def test_self_edges_ignored():
    g = CodebaseGraph(
        directory_tree="root/",
        import_edges=[_edge("a.py", "a.py")],
    )
    assert fan_in(g) == {}


def test_merges_ast_and_llm_edges():
    g = CodebaseGraph(
        directory_tree="root/",
        deterministic_edges=[_edge("a.py", "core.py")],
        import_edges=[_edge("b.py", "core.py")],
    )
    # Distinct importers across both edge sources.
    assert fan_in(g)["core.py"] == 2


def test_normalises_dot_slash_paths():
    g = CodebaseGraph(
        directory_tree="root/",
        import_edges=[_edge("./a.py", "./core.py"), _edge("b.py", "core.py")],
    )
    # ./core.py and core.py are the same target; ./a.py and b.py two importers.
    assert fan_in(g)["core.py"] == 2


def test_top_fan_in_sorted_and_capped():
    g = CodebaseGraph(
        directory_tree="root/",
        import_edges=[
            _edge("a.py", "hot.py"),
            _edge("b.py", "hot.py"),
            _edge("c.py", "hot.py"),
            _edge("a.py", "warm.py"),
            _edge("b.py", "warm.py"),
            _edge("a.py", "cold.py"),
        ],
    )
    ranked = top_fan_in(g, limit=2)
    assert ranked == [("hot.py", 3), ("warm.py", 2)]


def test_top_fan_in_tiebreak_is_path():
    g = CodebaseGraph(
        directory_tree="root/",
        import_edges=[_edge("x.py", "b.py"), _edge("x.py", "a.py")],
    )
    # Both imported once → sorted by path.
    assert top_fan_in(g) == [("a.py", 1), ("b.py", 1)]


def test_self_import_does_not_inflate_fan_in():
    # A file importing itself must NOT count toward its own blast radius. This is
    # the deliberate difference from the pre-extraction MCP `most_imported`,
    # which counted the self-edge (a file cannot be part of its own blast radius).
    g = CodebaseGraph(
        directory_tree="root/",
        import_edges=[_edge("a.py", "a.py"), _edge("b.py", "a.py")],
    )
    assert top_fan_in(g) == [("a.py", 1)]  # only b.py, not a.py itself


def test_matches_distinct_importer_semantics_across_sources():
    # The pre-extraction overview counted distinct *importing files* over the
    # AST∪LLM union; the same (a,b) pair via both import and from kinds is one
    # importer. degree.fan_in must agree.
    g = CodebaseGraph(
        directory_tree="root/",
        deterministic_edges=[_edge("a.py", "core.py", "import")],
        import_edges=[_edge("a.py", "core.py", "from"), _edge("b.py", "core.py")],
    )
    assert fan_in(g)["core.py"] == 2  # a.py (once) + b.py
