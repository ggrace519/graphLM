"""Tests for the render module."""

from pathlib import Path
from tempfile import TemporaryDirectory

from graphlm.models import (
    ArchitectureNote,
    CodebaseGraph,
    DBColumn,
    DBTable,
    DataFlowEdge,
    ImportEdge,
    ModuleDescription,
    QuickReference,
    TestMapping,
)
from graphlm.render import render_json, render_markdown, write_outputs


class TestRenderMarkdown:
    def test_empty_graph(self):
        graph = CodebaseGraph(directory_tree="root/\n")
        md = render_markdown(graph)
        assert "Codebase Graph" in md
        assert "root/" in md

    def test_with_import_edges(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            import_edges=[
                ImportEdge(from_path="a.py", to_path="b.py", kind="import"),
                ImportEdge(from_path="c.py", to_path="b.py", kind="from"),
            ],
        )
        md = render_markdown(graph)
        assert "| From | To | Kind |" in md
        assert "`a.py`" in md
        assert "import" in md

    def test_with_modules(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            modules=[
                ModuleDescription(path="main.py", name="Main", description="Entry point"),
                ModuleDescription(path="lib.py", name="Lib", description="Library"),
            ],
        )
        md = render_markdown(graph)
        assert "| Path | Name | Description |" in md
        assert "main.py" in md
        assert "Entry point" in md

    def test_with_database_schema(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            database_schema=[
                DBTable(
                    name="users",
                    columns=[
                        DBColumn(name="id", type="INTEGER", constraints="PRIMARY KEY"),
                        DBColumn(name="email", type="TEXT", constraints="NOT NULL"),
                    ],
                    description="User accounts",
                )
            ],
        )
        md = render_markdown(graph)
        assert "users" in md
        assert "User accounts" in md
        assert "`id`" in md
        assert "INTEGER" in md

    def test_with_data_flow(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            data_flow=[
                DataFlowEdge(source="API", destination="DB", description="Queries"),
            ],
        )
        md = render_markdown(graph)
        assert "| Source | Destination | Description |" in md
        assert "API" in md
        assert "DB" in md

    def test_with_quick_reference(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            quick_reference=[
                QuickReference(query="app factory", location="main.py"),
            ],
        )
        md = render_markdown(graph)
        assert "| Find | Location |" in md
        assert "app factory" in md
        assert "main.py" in md

    def test_with_test_organization(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            test_organization=[
                TestMapping(file="test_main.py", covers="App factory"),
            ],
        )
        md = render_markdown(graph)
        assert "| Test File | Covers |" in md
        assert "test_main.py" in md

    def test_with_architecture_notes(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            architecture_notes=[
                ArchitectureNote(note="No ORM used"),
                ArchitectureNote(note="Vanilla HTML/CSS/JS"),
            ],
        )
        md = render_markdown(graph)
        assert "No ORM used" in md
        assert "Vanilla HTML/CSS/JS" in md

    def test_markdown_has_newline_terminator(self):
        graph = CodebaseGraph(directory_tree="root/\n")
        md = render_markdown(graph)
        assert md.endswith("\n")


class TestRenderJson:
    def test_serializes_all_fields(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            import_edges=[ImportEdge(from_path="a.py", to_path="b.py", kind="import")],
            modules=[ModuleDescription(path="a.py", name="A", description="A module")],
            database_schema=[
                DBTable(name="t", columns=[DBColumn(name="c", type="INT")])
            ],
        )
        data = render_json(graph)
        assert b'"directory_tree"' in data
        assert b'"import_edges"' in data
        assert b'"modules"' in data
        assert b'"database_schema"' in data

    def test_null_database_schema_excluded(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            database_schema=None,
        )
        data = render_json(graph)
        assert b'"database_schema"' not in data

    def test_empty_lists_included(self):
        graph = CodebaseGraph(directory_tree="root/")
        data = render_json(graph)
        assert b'"import_edges": []' in data


class TestWriteOutputs:
    def test_writes_both_files(self):
        graph = CodebaseGraph(directory_tree="root/\n")
        with TemporaryDirectory() as tmpdir:
            md_path, json_path, html_path = write_outputs(graph, Path(tmpdir))
            assert md_path.exists()
            assert json_path.exists()
            assert html_path is not None
            assert html_path.exists()
            assert md_path.name.endswith(".md")
            assert json_path.name.endswith(".json")

    def test_no_html_when_disabled(self):
        graph = CodebaseGraph(directory_tree="root/\n")
        with TemporaryDirectory() as tmpdir:
            md_path, json_path, html_path = write_outputs(
                graph, Path(tmpdir), html=False
            )
            assert md_path.exists()
            assert json_path.exists()
            assert html_path is None

    def test_creates_output_directory(self):
        graph = CodebaseGraph(directory_tree="root/\n")
        with TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "nested" / "dir"
            md_path, json_path, html_path = write_outputs(graph, out)
            assert md_path.parent == out
            assert html_path.parent == out

    def test_custom_suffixes(self):
        graph = CodebaseGraph(directory_tree="root/\n")
        with TemporaryDirectory() as tmpdir:
            md_path, json_path, html_path = write_outputs(
                graph, Path(tmpdir), md_suffix="graph", json_suffix="graph"
            )
            assert md_path.name == "graph.md"
            assert json_path.name == "graph.json"
