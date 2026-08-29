"""Tests for the Pydantic models."""

import pytest
from pydantic import ValidationError

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


class TestImportEdge:
    def test_valid_import_edge(self):
        edge = ImportEdge(from_path="a.py", to_path="b.py", kind="import")
        assert edge.from_path == "a.py"
        assert edge.to_path == "b.py"
        assert edge.kind == "import"

    def test_all_kind_values(self):
        for kind in ("import", "from", "register", "include", "uses"):
            edge = ImportEdge(from_path="a.py", to_path="b.py", kind=kind)
            assert edge.kind == kind

    def test_valid_kind_accepted(self):
        edge = ImportEdge(from_path="a.py", to_path="b.py", kind="custom_kind")
        assert edge.kind == "custom_kind"


class TestModuleDescription:
    def test_valid_module(self):
        mod = ModuleDescription(path="app/main.py", name="Main", description="App factory")
        assert mod.path == "app/main.py"
        assert mod.name == "Main"
        assert mod.description == "App factory"


class TestDataFlowEdge:
    def test_valid_flow(self):
        flow = DataFlowEdge(source="API", destination="DB", description="Queries")
        assert flow.source == "API"
        assert flow.destination == "DB"

    def test_flow_with_paths(self):
        flow = DataFlowEdge(
            source="routes/users.py",
            destination="services/user_service.py",
            description="User creation requests",
        )
        assert "users" in flow.source
        assert "user_service" in flow.destination


class TestDBColumn:
    def test_column_with_constraints(self):
        col = DBColumn(name="id", type="INTEGER", constraints="PRIMARY KEY")
        assert col.name == "id"
        assert col.type == "INTEGER"
        assert col.constraints == "PRIMARY KEY"

    def test_column_without_constraints(self):
        col = DBColumn(name="name", type="TEXT")
        assert col.constraints is None


class TestDBTable:
    def test_valid_table(self):
        table = DBTable(
            name="users",
            columns=[
                DBColumn(name="id", type="INTEGER", constraints="PRIMARY KEY"),
                DBColumn(name="email", type="TEXT", constraints="NOT NULL UNIQUE"),
            ],
            description="User accounts",
        )
        assert table.name == "users"
        assert len(table.columns) == 2
        assert table.description == "User accounts"

    def test_table_without_columns(self):
        table = DBTable(name="empty", columns=[])
        assert table.columns == []


class TestTestMapping:
    def test_valid_mapping(self):
        tm = TestMapping(file="tests/test_main.py", covers="App factory and middleware")
        assert tm.file == "tests/test_main.py"


class TestArchitectureNote:
    def test_valid_note(self):
        note = ArchitectureNote(note="No ORM used")
        assert note.note == "No ORM used"


class TestQuickReference:
    def test_valid_reference(self):
        qr = QuickReference(query="app factory", location="softreq/main.py")
        assert qr.query == "app factory"


class TestCodebaseGraph:
    def test_empty_graph(self):
        graph = CodebaseGraph(directory_tree="root/\n")
        assert graph.directory_tree == "root/\n"
        assert graph.import_edges == []
        assert graph.modules == []
        assert graph.database_schema is None

    def test_full_graph(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            import_edges=[ImportEdge(from_path="a.py", to_path="b.py", kind="import")],
            modules=[ModuleDescription(path="a.py", name="A", description="Module A")],
            data_flow=[DataFlowEdge(source="A", destination="B", description="Data")],
            database_schema=[
                DBTable(name="users", columns=[DBColumn(name="id", type="INTEGER")])
            ],
            test_organization=[TestMapping(file="test_a.py", covers="Module A")],
            architecture_notes=[ArchitectureNote(note="No ORM")],
            quick_reference=[QuickReference(query="app", location="main.py")],
        )
        assert len(graph.import_edges) == 1
        assert len(graph.modules) == 1
        assert len(graph.database_schema) == 1
        assert len(graph.test_organization) == 1
        assert len(graph.architecture_notes) == 1
        assert len(graph.quick_reference) == 1

    def test_serialization(self):
        graph = CodebaseGraph(
            directory_tree="root/",
            import_edges=[ImportEdge(from_path="a.py", to_path="b.py", kind="import")],
        )
        json_str = graph.model_dump_json()
        parsed = CodebaseGraph.model_validate_json(json_str)
        assert len(parsed.import_edges) == 1
        assert parsed.import_edges[0].from_path == "a.py"
