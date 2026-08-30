"""Tests for the html_render module."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from graphlm.html_render import (
    _build_links,
    _build_nodes,
    _directory_color,
    render_html,
)
from graphlm.models import (
    CodebaseGraph,
    FileSummary,
    ImportEdge,
    ModuleDescription,
    Symbol,
)
from graphlm.render import write_outputs


class TestDirectoryColor:
    def test_returns_hex_color(self):
        color = _directory_color("app")
        assert color.startswith("#")
        assert len(color) == 7

    def test_deterministic(self):
        assert _directory_color("app") == _directory_color("app")

    def test_different_dirs_different_colors(self):
        # Use long, distinct directory names that hash to different colors
        assert _directory_color("application_directory") != _directory_color("testing_directory")

    def test_consistent_across_calls(self):
        results = [_directory_color("lib") for _ in range(10)]
        assert len(set(results)) == 1


class TestBuildNodes:
    def test_empty_graph_no_nodes(self):
        graph = CodebaseGraph(directory_tree="root/")
        nodes = _build_nodes(graph)
        assert nodes == []

    def test_modules_become_nodes(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            modules=[
                ModuleDescription(path="app/__init__.py", name="App", description="App factory"),
                ModuleDescription(path="app/main.py", name="main", description="Entry point"),
            ],
        )
        nodes = _build_nodes(graph)
        assert len(nodes) == 2
        assert nodes[0]["type"] == "module"
        assert nodes[0]["r"] == 8
        assert nodes[0]["name"] == "App"

    def test_entry_points_become_nodes(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            entry_points=[
                {
                    "path": "app/main.py",
                    "name": "main",
                    "kind": "main",
                    "description": "CLI entry point",
                }
            ],
        )
        nodes = _build_nodes(graph)
        assert len(nodes) == 1
        assert nodes[0]["type"] == "entry_point"
        assert nodes[0]["r"] == 12

    def test_file_summaries_become_nodes(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            file_summaries=[
                FileSummary(path="app/main.py", summary="The main module"),
            ],
        )
        nodes = _build_nodes(graph)
        assert len(nodes) == 1
        assert nodes[0]["type"] == "file_summary"
        assert nodes[0]["r"] == 5

    def test_all_three_types_together(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            modules=[ModuleDescription(path="a.py", name="A", description="A")],
            entry_points=[{"path": "b.py", "name": "b", "kind": "main", "description": "b"}],
            file_summaries=[FileSummary(path="c.py", summary="C")],
        )
        nodes = _build_nodes(graph)
        assert len(nodes) == 3
        types = {n["type"] for n in nodes}
        assert types == {"module", "entry_point", "file_summary"}

    def test_nodes_have_color(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            modules=[ModuleDescription(path="app/main.py", name="A", description="A")],
        )
        nodes = _build_nodes(graph)
        assert nodes[0]["color"].startswith("#")

    def test_nodes_have_description(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            modules=[ModuleDescription(path="a.py", name="A", description="Description text")],
        )
        nodes = _build_nodes(graph)
        assert nodes[0]["description"] == "Description text"

    def test_nodes_have_path(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            modules=[ModuleDescription(path="lib/utils.py", name="utils", description="U")],
        )
        nodes = _build_nodes(graph)
        assert nodes[0]["path"] == "lib/utils.py"


class TestBuildLinks:
    def test_import_edges_become_links(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            import_edges=[
                ImportEdge(from_path="app/main.py", to_path="app/routes.py", kind="import"),
            ],
        )
        links = _build_links(graph)
        assert len(links) == 1
        assert links[0]["type"] == "import"
        assert links[0]["source"] == "app/main.py"
        assert links[0]["target"] == "app/routes.py"
        assert links[0]["dash"] is None

    def test_data_flow_become_links(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            data_flow=[
                {"source": "API", "destination": "DB", "description": "Queries"},
            ],
        )
        links = _build_links(graph)
        assert len(links) == 1
        assert links[0]["type"] == "data_flow"
        assert links[0]["dash"] == "5,5"

    def test_empty_graph_no_links(self):
        graph = CodebaseGraph(directory_tree="root/")
        links = _build_links(graph)
        assert links == []

    def test_multiple_edges(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            import_edges=[
                ImportEdge(from_path="a.py", to_path="b.py", kind="import"),
                ImportEdge(from_path="b.py", to_path="c.py", kind="from"),
            ],
            data_flow=[
                {"source": "X", "destination": "Y", "description": "Data"},
            ],
        )
        links = _build_links(graph)
        assert len(links) == 3


class TestRenderHtml:
    def test_produces_valid_html(self):
        graph = CodebaseGraph(directory_tree="test/")
        html = render_html(graph)
        assert html.strip().startswith("<!DOCTYPE html>")
        assert "</html>" in html
        assert "</head>" in html
        assert "</body>" in html

    def test_embeds_d3_cdn(self):
        graph = CodebaseGraph(directory_tree="test/")
        html = render_html(graph)
        assert "d3.v7.min.js" in html

    def test_embeds_graph_data(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            modules=[
                ModuleDescription(path="app/main.py", name="Main", description="Entry point"),
            ],
        )
        html = render_html(graph)
        data_start = html.index("const graphData = ") + len("const graphData = ")
        data_end = html.index(";\nconst _PALETTE")
        data = json.loads(html[data_start:data_end])
        assert len(data["nodes"]) == 1
        assert data["nodes"][0]["name"] == "Main"

    def test_modules_included_as_nodes(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            modules=[
                ModuleDescription(path="app/__init__.py", name="App", description="Factory"),
                ModuleDescription(path="app/main.py", name="main", description="Entry"),
            ],
        )
        html = render_html(graph)
        data = json.loads(
            html[html.index("const graphData = ") + len("const graphData = "):html.index(";\nconst _PALETTE")]
        )
        types = [n["type"] for n in data["nodes"]]
        assert "module" in types
        assert len([n for n in data["nodes"] if n["type"] == "module"]) == 2

    def test_entry_points_included(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            entry_points=[{"path": "app/main.py", "name": "main", "kind": "main", "description": "CLI"}],
        )
        html = render_html(graph)
        data = json.loads(
            html[html.index("const graphData = ") + len("const graphData = "):html.index(";\nconst _PALETTE")]
        )
        assert any(n["type"] == "entry_point" for n in data["nodes"])

    def test_import_edges_become_links(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            import_edges=[
                ImportEdge(from_path="a.py", to_path="b.py", kind="import"),
            ],
        )
        html = render_html(graph)
        data = json.loads(
            html[html.index("const graphData = ") + len("const graphData = "):html.index(";\nconst _PALETTE")]
        )
        assert len(data["links"]) == 1
        assert data["links"][0]["type"] == "import"

    def test_empty_graph_no_nodes(self):
        graph = CodebaseGraph(directory_tree="root/")
        html = render_html(graph)
        data = json.loads(
            html[html.index("const graphData = ") + len("const graphData = "):html.index(";\nconst _PALETTE")]
        )
        assert data["nodes"] == []
        assert data["links"] == []

    def test_empty_graph_still_valid_html(self):
        graph = CodebaseGraph(directory_tree="root/")
        html = render_html(graph)
        assert html.strip().startswith("<!DOCTYPE html>")
        assert "const graphData" in html

    def test_large_graph_no_errors(self):
        modules = []
        for i in range(150):
            modules.append(
                ModuleDescription(
                    path=f"pkg{i}/mod{i}.py",
                    name=f"Module{i}",
                    description=f"Module {i} description",
                )
            )
        graph = CodebaseGraph(
            directory_tree="root/",
            modules=modules,
        )
        html = render_html(graph)
        data = json.loads(
            html[html.index("const graphData = ") + len("const graphData = "):html.index(";\nconst _PALETTE")]
        )
        assert len(data["nodes"]) == 150

    def test_html_contains_force_simulation(self):
        graph = CodebaseGraph(directory_tree="test/")
        html = render_html(graph)
        assert "forceSimulation" in html

    def test_html_contains_search_box(self):
        graph = CodebaseGraph(directory_tree="test/")
        html = render_html(graph)
        assert "Search nodes" in html

    def test_html_contains_theme_toggle(self):
        graph = CodebaseGraph(directory_tree="test/")
        html = render_html(graph)
        assert "Toggle Theme" in html

    def test_html_contains_legend(self):
        graph = CodebaseGraph(directory_tree="test/")
        html = render_html(graph)
        assert "Legend" in html

    def test_html_contains_tooltip(self):
        graph = CodebaseGraph(directory_tree="test/")
        html = render_html(graph)
        assert "tooltip" in html

    def test_html_contains_zoom(self):
        graph = CodebaseGraph(directory_tree="test/")
        html = render_html(graph)
        assert "d3.zoom" in html

    def test_file_summaries_with_symbols(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            file_summaries=[
                FileSummary(
                    path="app/models.py",
                    summary="Data models",
                    symbols=[
                        Symbol(name="User", kind="class", description="User model"),
                    ],
                ),
            ],
        )
        html = render_html(graph)
        data = json.loads(
            html[html.index("const graphData = ") + len("const graphData = "):html.index(";\nconst _PALETTE")]
        )
        assert len(data["nodes"]) == 1
        assert data["nodes"][0]["type"] == "file_summary"
        assert "Data models" in data["nodes"][0]["description"]

    def test_domcontentloaded_calls_initgraph(self):
        graph = CodebaseGraph(directory_tree="test/")
        html = render_html(graph)
        marker = "window.addEventListener('DOMContentLoaded'"
        assert marker in html
        after_load = html.split(marker, 1)[1]
        assert "initGraph()" in after_load

    def test_initgraph_does_not_call_itself(self):
        graph = CodebaseGraph(directory_tree="test/")
        html = render_html(graph)
        after_def = html.split("function initGraph()", 1)[1]
        load_markers = (
            "window.addEventListener('DOMContentLoaded'",
            "DOMContentLoaded",
        )
        cut = len(after_def)
        for marker in load_markers:
            idx = after_def.find(marker)
            if idx != -1:
                cut = min(cut, idx)
        body = after_def[:cut]
        assert "initGraph()" not in body
        after_load = after_def[cut:]
        assert "DOMContentLoaded" in after_load
        assert "initGraph()" in after_load


class TestWriteOutputsWithHtml:
    def test_writes_html_by_default(self):
        graph = CodebaseGraph(directory_tree="root/\n")
        with TemporaryDirectory() as tmpdir:
            md_path, json_path, html_path = write_outputs(graph, Path(tmpdir))
            assert md_path.exists()
            assert json_path.exists()
            assert html_path is not None
            assert html_path.exists()
            assert html_path.name == "graph.html"
            assert html_path.read_text(encoding="utf-8").startswith("<!DOCTYPE")

    def test_no_html_when_disabled(self):
        graph = CodebaseGraph(directory_tree="root/\n")
        with TemporaryDirectory() as tmpdir:
            _, _, html_path = write_outputs(graph, Path(tmpdir), html=False)
            assert html_path is None

    def test_custom_html_suffix(self):
        graph = CodebaseGraph(directory_tree="root/\n")
        with TemporaryDirectory() as tmpdir:
            _, _, html_path = write_outputs(
                graph, Path(tmpdir), html=True, html_suffix="viz"
            )
            assert html_path is not None
            assert html_path.name == "viz.html"

    def test_creates_output_directory(self):
        graph = CodebaseGraph(directory_tree="root/\n")
        with TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "nested" / "dir"
            _, _, html_path = write_outputs(graph, out)
            assert html_path.parent == out

    def test_html_contains_graph_data(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            modules=[
                ModuleDescription(path="app/main.py", name="Main", description="Entry"),
            ],
        )
        with TemporaryDirectory() as tmpdir:
            _, _, html_path = write_outputs(graph, Path(tmpdir))
            html = html_path.read_text(encoding="utf-8")
            assert "Main" in html
            assert "Entry" in html
            assert "app/main.py" in html

    def test_html_is_self_contained(self):
        graph = CodebaseGraph(directory_tree="root/\n")
        with TemporaryDirectory() as tmpdir:
            _, _, html_path = write_outputs(graph, Path(tmpdir))
            html = html_path.read_text(encoding="utf-8")
            assert "<style>" in html
            assert "d3js.org" in html
