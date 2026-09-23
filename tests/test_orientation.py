"""Tests for the GRAPH.md orientation block (``graphlm.orientation``)."""

from __future__ import annotations

from graphlm.models import (
    CodebaseGraph,
    Cycle,
    EntryPoint,
    ImportEdge,
)
from graphlm.orientation import render_orientation
from graphlm.render import render_markdown


def _edge(a: str, b: str, kind: str = "import") -> ImportEdge:
    return ImportEdge(from_path=a, to_path=b, kind=kind)


def _block(graph: CodebaseGraph, importance: str | None = None) -> str:
    return "\n".join(render_orientation(graph, importance))


def test_empty_graph_renders_nothing():
    assert render_orientation(CodebaseGraph(directory_tree="root/")) == []


def test_entry_points_listed():
    g = CodebaseGraph(
        directory_tree="root/",
        entry_points=[
            EntryPoint(path="cli.py", name="main", kind="cli_command", description=""),
        ],
    )
    block = _block(g)
    assert "## Orientation" in block
    assert "**Entry points:**" in block
    assert "`cli.py::main`" in block


def test_entry_points_capped_with_more_marker():
    eps = [
        EntryPoint(path=f"e{i}.py", name="f", kind="factory", description="")
        for i in range(8)
    ]
    g = CodebaseGraph(directory_tree="root/", entry_points=eps)
    block = _block(g)
    assert "(+2 more)" in block  # 8 total, 6 shown


def test_cycles_split_production_and_test():
    g = CodebaseGraph(
        directory_tree="root/",
        import_cycles=[
            Cycle(nodes=["a.py", "b.py"], edges=[], length=2, risk_score=2.0),
            Cycle(
                nodes=["tests/c.py", "tests/d.py"],
                edges=[],
                length=2,
                risk_score=1.0,
                test_only=True,
            ),
        ],
    )
    block = _block(g)
    assert "**Import cycles:** 1 production, 1 in test code" in block


def test_cycles_all_test_only():
    g = CodebaseGraph(
        directory_tree="root/",
        import_cycles=[
            Cycle(
                nodes=["tests/c.py", "tests/d.py"],
                edges=[],
                length=2,
                risk_score=1.0,
                test_only=True,
            ),
        ],
    )
    block = _block(g)
    assert "**Import cycles:** 1 in test code" in block
    assert "production" not in block


def test_most_imported_listed():
    g = CodebaseGraph(
        directory_tree="root/",
        import_edges=[_edge("a.py", "core.py"), _edge("b.py", "core.py")],
    )
    block = _block(g)
    assert "**Most imported (blast radius):**" in block
    assert "`core.py` (2)" in block
    # Never mislabelled as "importance" (ADR-015).
    assert "importance" not in block.lower()


def test_importance_line_included_when_present():
    g = CodebaseGraph(
        directory_tree="root/",
        entry_points=[
            EntryPoint(path="cli.py", name="main", kind="cli_command", description=""),
        ],
    )
    block = _block(g, importance="most load-bearing: core.py (0.90)")
    # Only the label is bold, matching the other bullets.
    assert "- **Most load-bearing:** core.py (0.90)" in block


def test_importance_line_without_colon_rendered_verbatim():
    # Defensive fallback: an importance clause with no "label: value" shape is
    # rendered as a plain bullet rather than mangled.
    g = CodebaseGraph(
        directory_tree="root/",
        entry_points=[
            EntryPoint(path="cli.py", name="main", kind="cli_command", description=""),
        ],
    )
    block = _block(g, importance="no clear leader")
    assert "- no clear leader" in block


def test_block_sits_between_header_and_directory_tree():
    g = CodebaseGraph(
        directory_tree="root/",
        entry_points=[
            EntryPoint(path="cli.py", name="main", kind="cli_command", description=""),
        ],
    )
    md = render_markdown(g)
    assert (
        md.index("# Codebase Graph")
        < md.index("## Orientation")
        < md.index("## Directory Tree")
    )


def test_minimal_graph_has_no_orientation_section():
    # A graph with a tree but no edges/cycles/entry points → no block, so the
    # pre-feature top-of-document shape is preserved.
    md = render_markdown(CodebaseGraph(directory_tree="root/"))
    assert "## Orientation" not in md
