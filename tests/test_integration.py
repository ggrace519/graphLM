"""Integration tests for the full pipeline (mocked LLM, no real API calls)."""

import json
from pathlib import Path

import pytest
from httpx import Response

from graphlm import generate_graph
from graphlm.llm import GraphLLError
from graphlm.models import CodebaseGraph


def _mock_pass1_response(httpx_mock, requested_files):
    """Mock pass 1 LLM response returning requested file paths."""
    body = {"choices": [{"message": {"content": json.dumps({"requested_files": requested_files})}, "index": 0}]}
    httpx_mock.add_response(json=body)


def _mock_pass2_response(httpx_mock, graph_data):
    """Mock pass 2 LLM response returning a complete graph."""
    body = {"choices": [{"message": {"content": json.dumps(graph_data)}, "index": 0}]}
    httpx_mock.add_response(json=body)


def _make_graph(**overrides):
    """Create a minimal valid graph dict, with optional overrides."""
    base = {
        "directory_tree": "test-project/\n",
        "import_edges": [],
        "modules": [],
        "data_flow": [],
        "database_schema": None,
        "test_organization": [],
        "architecture_notes": [{"note": "test"}],
        "quick_reference": [],
    }
    base.update(overrides)
    return base


class TestFullPipeline:
    def test_small_project_full_pipeline(self, httpx_mock, small_project, tmp_path):
        """End-to-end: small project scan → LLM passes → graph output."""
        _mock_pass1_response(httpx_mock, ["main.py", "mylib/helpers.py"])
        graph = _make_graph()
        _mock_pass2_response(httpx_mock, graph)

        result = generate_graph(
            small_project,
            base_url="http://test.local/v1",
            api_key="test-key",
            model="test-model",
            output_dir=tmp_path,
            dry_run=False,
        )

        assert isinstance(result.graph, CodebaseGraph)
        assert result.files_analyzed > 0
        # Verify outputs were written
        md_files = list(tmp_path.glob("*.md"))
        json_files = list(tmp_path.glob("*.json"))
        assert len(md_files) >= 1
        assert len(json_files) >= 1

    def test_small_project_dry_run(self, httpx_mock, small_project, tmp_path):
        """Dry run should NOT call the LLM."""
        result = generate_graph(
            small_project,
            base_url="http://test.local/v1",
            api_key="test-key",
            model="test-model",
            dry_run=True,
        )

        # Should have graph with tree but no LLM data
        assert "test-project" in result.graph.directory_tree or "small_project" in result.graph.directory_tree
        assert len(result.graph.architecture_notes) == 1
        assert "DRY RUN" in result.graph.architecture_notes[0].note
        # No LLM calls should have been made
        assert len(httpx_mock.get_requests()) == 0

    def test_medium_project_with_imports(self, httpx_mock, medium_project):
        """Test that import edges are captured in the graph."""
        _mock_pass1_response(httpx_mock, [
            "pyproject.toml",
            "src/__init__.py",
            "src/core/__init__.py",
            "src/utils/__init__.py",
        ])
        graph = _make_graph(
            import_edges=[
                {"from_path": "src/__init__.py", "to_path": "src/core/__init__.py", "kind": "import"},
                {"from_path": "src/__init__.py", "to_path": "src/utils/__init__.py", "kind": "import"},
            ],
            modules=[
                {"path": "src/core/__init__.py", "name": "Core Engine", "description": "Main processing engine"},
                {"path": "src/utils/__init__.py", "name": "Utils", "description": "Utility functions"},
            ],
        )
        _mock_pass2_response(httpx_mock, graph)

        result = generate_graph(
            medium_project,
            base_url="http://test.local/v1",
            api_key="test-key",
            model="test-model",
        )

        assert len(result.graph.import_edges) == 2
        assert len(result.graph.modules) == 2

    def test_medium_project_with_database(self, httpx_mock, medium_project):
        """Test that database schema is captured."""
        _mock_pass1_response(httpx_mock, ["pyproject.toml", "migrations/001_initial.sql"])
        graph = _make_graph(
            database_schema=[
                {
                    "name": "items",
                    "columns": [
                        {"name": "id", "type": "INTEGER", "constraints": "PRIMARY KEY"},
                        {"name": "name", "type": "TEXT", "constraints": "NOT NULL"},
                    ],
                    "description": "Items table",
                },
            ],
        )
        _mock_pass2_response(httpx_mock, graph)

        result = generate_graph(
            medium_project,
            base_url="http://test.local/v1",
            api_key="test-key",
            model="test-model",
        )

        assert result.graph.database_schema is not None
        assert len(result.graph.database_schema) == 1
        assert result.graph.database_schema[0].name == "items"

    def test_large_project_full_pipeline(self, httpx_mock, large_project, tmp_path):
        """End-to-end: large project with many files."""
        # LLM requests a subset of files
        requested = [
            "pyproject.toml",
            "README.md",
            "app/main.py",
            "app/__init__.py",
            "app/models/user.py",
            "app/models/item.py",
            "app/routes/users.py",
            "app/routes/items.py",
            "app/services/auth.py",
            "app/services/user_service.py",
            "app/services/item_service.py",
            "migrations/001_create_users.sql",
            "migrations/002_create_items.sql",
            "templates/base.html",
            "static/css/app.css",
            "static/js/app.js",
        ]
        _mock_pass1_response(httpx_mock, requested)

        graph = _make_graph(
            import_edges=[
                {"from_path": "app/main.py", "to_path": "app/routes/users.py", "kind": "include"},
                {"from_path": "app/main.py", "to_path": "app/routes/items.py", "kind": "include"},
                {"from_path": "app/routes/users.py", "to_path": "app/services/user_service.py", "kind": "import"},
                {"from_path": "app/services/auth.py", "to_path": "app/services/user_service.py", "kind": "uses"},
            ],
            modules=[
                {"path": "app/main.py", "name": "App Factory", "description": "FastAPI app assembly"},
                {"path": "app/routes/users.py", "name": "User Routes", "description": "User API endpoints"},
                {"path": "app/routes/items.py", "name": "Item Routes", "description": "Item API endpoints"},
                {"path": "app/services/auth.py", "name": "Auth Service", "description": "Password hashing"},
                {"path": "app/services/user_service.py", "name": "User Service", "description": "User business logic"},
                {"path": "app/services/item_service.py", "name": "Item Service", "description": "Item business logic"},
            ],
            data_flow=[
                {"source": "User Routes", "destination": "User Service", "description": "User creation requests"},
                {"source": "Item Routes", "destination": "Item Service", "description": "Item creation requests"},
                {"source": "Auth Service", "destination": "User Service", "description": "Password hashing"},
            ],
            database_schema=[
                {
                    "name": "users",
                    "columns": [
                        {"name": "id", "type": "INTEGER", "constraints": "PRIMARY KEY"},
                        {"name": "email", "type": "TEXT", "constraints": "NOT NULL UNIQUE"},
                    ],
                    "description": "User accounts",
                },
                {
                    "name": "items",
                    "columns": [
                        {"name": "id", "type": "INTEGER", "constraints": "PRIMARY KEY"},
                        {"name": "title", "type": "TEXT", "constraints": "NOT NULL"},
                    ],
                    "description": "User items",
                },
            ],
            test_organization=[
                {"file": "tests/test_users.py", "covers": "User schema validation"},
                {"file": "tests/test_auth.py", "covers": "Password hashing and verification"},
                {"file": "tests/test_items.py", "covers": "Item schema validation"},
            ],
            architecture_notes=[
                {"note": "FastAPI with Jinja2 templates"},
                {"note": "SQLite with raw SQL migrations"},
                {"note": "Service layer pattern for business logic"},
            ],
            quick_reference=[
                {"query": "app factory", "location": "app/main.py"},
                {"query": "user routes", "location": "app/routes/users.py"},
                {"query": "item routes", "location": "app/routes/items.py"},
                {"query": "password hashing", "location": "app/services/auth.py"},
            ],
        )
        _mock_pass2_response(httpx_mock, graph)

        result = generate_graph(
            large_project,
            base_url="http://test.local/v1",
            api_key="test-key",
            model="test-model",
            output_dir=tmp_path,
            include_tests=True,
        )

        assert len(result.graph.import_edges) == 4
        assert len(result.graph.modules) == 6
        assert len(result.graph.data_flow) == 3
        assert len(result.graph.database_schema) == 2
        assert len(result.graph.test_organization) == 3
        assert len(result.graph.architecture_notes) == 3
        assert len(result.graph.quick_reference) == 4

    def test_invalid_pass1_json_raises(self, httpx_mock, small_project):
        """If pass 1 returns invalid JSON, should raise."""
        httpx_mock.add_response(
            json={"choices": [{"message": {"content": "not json"}, "index": 0}]}
        )
        with pytest.raises(GraphLLError) as exc_info:
            generate_graph(
                small_project,
                base_url="http://test.local/v1",
                api_key="test-key",
                model="test-model",
            )
        assert "not valid JSON" in str(exc_info.value).lower() or "Could not extract JSON" in str(exc_info.value)

    def test_incomplete_config_raises(self, small_project):
        """If only some config args are provided, should raise."""
        with pytest.raises(ValueError) as exc_info:
            generate_graph(
                small_project,
                base_url="http://test.local/v1",
                api_key="test-key",
                # model is missing
            )
        assert "all three must be provided" in str(exc_info.value)
