"""Tests for the AST parser module."""

from __future__ import annotations

from pathlib import Path

import pytest

from graphlm.models import ImportEdge
from graphlm.parser import (
    ParsedFile,
    build_dependency_graph,
    detect_import_cycles,
    detect_language,
    parse_file,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestDetectLanguage:
    def test_python(self):
        assert detect_language(Path("foo.py")) == "python"

    def test_javascript(self):
        assert detect_language(Path("foo.js")) == "javascript"

    def test_typescript(self):
        assert detect_language(Path("foo.ts")) == "typescript"

    def test_jsx(self):
        assert detect_language(Path("foo.jsx")) == "javascript"

    def test_tsx(self):
        assert detect_language(Path("foo.tsx")) == "typescript"

    def test_unsupported(self):
        assert detect_language(Path("foo.txt")) is None
        assert detect_language(Path("foo.md")) is None
        assert detect_language(Path("foo.json")) is None

    def test_case_insensitive(self):
        assert detect_language(Path("FOO.PY")) == "python"


class TestParseFile:
    def test_parse_python_file(self, small_project):
        main = small_project / "main.py"
        result = parse_file(main)
        assert result is not None
        assert isinstance(result, ParsedFile)
        assert isinstance(result.imports, list)
        assert isinstance(result.functions, list)
        assert isinstance(result.exports, list)
        assert isinstance(result.call_sites, list)

    def test_parse_main_py_large_project(self, large_project):
        main = large_project / "app" / "main.py"
        result = parse_file(main)
        assert result is not None
        assert len(result.imports) >= 3
        import_paths = {e.to_path for e in result.imports}
        assert "app/routes.py" in import_paths
        assert "app/services/auth.py" in import_paths

    def test_parse_routes_items(self, large_project):
        items = large_project / "app" / "routes" / "items.py"
        result = parse_file(items)
        assert result is not None
        import_paths = {e.to_path for e in result.imports}
        assert "app/models/item.py" in import_paths
        assert "app/services/item_service.py" in import_paths

    def test_parse_user_service(self, large_project):
        svc = large_project / "app" / "services" / "user_service.py"
        result = parse_file(svc)
        assert result is not None
        import_paths = {e.to_path for e in result.imports}
        assert "app/models/user.py" in import_paths
        assert "app/services/auth.py" in import_paths

    def test_parse_file_no_functions(self, small_project):
        init = small_project / "mylib" / "__init__.py"
        result = parse_file(init)
        assert result is not None

    def test_parse_file_returns_none_for_unsupported_extension(self):
        assert parse_file(Path("/tmp/test.txt")) is None

    def test_parse_file_returns_none_for_nonexistent(self):
        assert parse_file(Path("/nonexistent/file.py")) is None

    def test_parse_file_returns_none_for_directory(self):
        assert parse_file(Path("/tmp")) is None

    def test_parse_file_returns_empty_for_syntax_errors(self):
        import tempfile
        with tempfile.NamedTemporaryFile(
            suffix=".py", mode="w", delete=False
        ) as f:
            f.write("def foo(\n    this is not valid python syntax\n")
            f.flush()
            fpath = Path(f.name)
        try:
            result = parse_file(fpath)
            assert result is not None
        finally:
            fpath.unlink()

    def test_parse_file_detects_functions(self, large_project):
        main = large_project / "app" / "main.py"
        result = parse_file(main)
        assert result is not None
        func_names = set(result.functions)
        assert "create_app" in func_names
        assert "healthz" in func_names

    def test_parse_file_detects_async_functions(self, large_project):
        items = large_project / "app" / "routes" / "items.py"
        result = parse_file(items)
        assert result is not None
        func_names = set(result.functions)
        assert "create_item_endpoint" in func_names
        assert "get_item_endpoint" in func_names

    def test_parse_file_detects_classes(self, small_project):
        helpers = small_project / "mylib" / "helpers.py"
        result = parse_file(helpers)
        assert result is not None

    def test_parse_file_exports_public_symbols(self, large_project):
        main = large_project / "app" / "main.py"
        result = parse_file(main)
        assert result is not None
        export_names = set(result.exports)
        assert "create_app" in export_names

    def test_parse_file_with_explicit_language(self):
        import tempfile
        with tempfile.NamedTemporaryFile(
            suffix=".py", mode="w", delete=False
        ) as f:
            f.write("import os\n\ndef hello():\n    pass\n")
            f.flush()
            fpath = Path(f.name)
        try:
            result = parse_file(fpath, language="python")
            assert result is not None
            assert len(result.imports) >= 1
        finally:
            fpath.unlink()


class TestBuildDependencyGraph:
    def test_build_graph_from_fragments(self, large_project):
        from graphlm.scanner import scan_project

        scan = scan_project(large_project, include_tests=True)
        edges = build_dependency_graph(scan.file_fragments, project_dir=large_project)
        assert isinstance(edges, list)
        assert len(edges) > 0
        for edge in edges:
            assert isinstance(edge, ImportEdge)
            assert edge.from_path
            assert edge.to_path
            assert edge.kind in ("import", "from")

    def test_build_graph_deduplicates(self, large_project):
        from graphlm.scanner import scan_project

        scan = scan_project(large_project, include_tests=False)
        edges = build_dependency_graph(scan.file_fragments, project_dir=large_project)
        seen = set()
        for edge in edges:
            key = (edge.from_path, edge.to_path, edge.kind)
            assert key not in seen
            seen.add(key)

    def test_build_graph_max_files(self, large_project):
        from graphlm.scanner import scan_project

        scan = scan_project(large_project, include_tests=True)
        edges = build_dependency_graph(scan.file_fragments, max_files=2, project_dir=large_project)
        assert len(edges) <= 20

    def test_build_graph_matches_fixture_imports(self, large_project):
        from graphlm.scanner import scan_project

        scan = scan_project(large_project, include_tests=False)
        edges = build_dependency_graph(scan.file_fragments, project_dir=large_project)
        edge_set = {(e.from_path, e.to_path) for e in edges}

        assert ("app/routes/items.py", "app/models/item.py") in edge_set
        assert ("app/routes/items.py", "app/services/item_service.py") in edge_set
        assert ("app/services/user_service.py", "app/services/auth.py") in edge_set


class TestImportCycles:
    def test_detect_no_cycles(self):
        edges = [
            ImportEdge(from_path="a.py", to_path="b.py", kind="from"),
            ImportEdge(from_path="b.py", to_path="c.py", kind="from"),
            ImportEdge(from_path="a.py", to_path="c.py", kind="from"),
        ]
        assert len(detect_import_cycles(edges)) == 0

    def test_detect_simple_cycle(self):
        edges = [
            ImportEdge(from_path="a.py", to_path="b.py", kind="from"),
            ImportEdge(from_path="b.py", to_path="a.py", kind="from"),
        ]
        cycles = detect_import_cycles(edges)
        assert len(cycles) >= 1
        assert "a.py" in cycles[0]
        assert "b.py" in cycles[0]

    def test_detect_complex_cycle(self):
        edges = [
            ImportEdge(from_path="a.py", to_path="b.py", kind="from"),
            ImportEdge(from_path="b.py", to_path="c.py", kind="from"),
            ImportEdge(from_path="c.py", to_path="a.py", kind="from"),
        ]
        cycles = detect_import_cycles(edges)
        assert len(cycles) >= 1
        assert "a.py" in cycles[0]
        assert "b.py" in cycles[0]
        assert "c.py" in cycles[0]

    def test_detect_partial_cycle(self):
        edges = [
            ImportEdge(from_path="a.py", to_path="b.py", kind="from"),
            ImportEdge(from_path="b.py", to_path="a.py", kind="from"),
            ImportEdge(from_path="c.py", to_path="a.py", kind="from"),
        ]
        cycles = detect_import_cycles(edges)
        assert len(cycles) >= 1
        for cycle in cycles:
            assert "c.py" not in cycle

    def test_detect_cycle_in_large_project(self, large_project):
        from graphlm.scanner import scan_project

        scan = scan_project(large_project, include_tests=False)
        edges = build_dependency_graph(scan.file_fragments, project_dir=large_project)
        cycles = detect_import_cycles(edges)
        assert isinstance(cycles, list)


class TestDeterministicEdgesMatchFixture:
    def test_main_py_deterministic_imports(self, large_project):
        from graphlm.scanner import scan_project

        scan = scan_project(large_project, include_tests=False)
        edges = build_dependency_graph(scan.file_fragments, project_dir=large_project)
        main_edges = [e for e in edges if "app/main.py" in e.from_path]
        main_targets = {e.to_path for e in main_edges}
        assert "app/routes.py" in main_targets
        assert "app/services/auth.py" in main_targets

    def test_all_py_files_parsed(self, large_project):
        py_files = list(large_project.rglob("*.py"))
        assert len(py_files) > 0
        for fpath in py_files:
            result = parse_file(fpath)
            assert result is not None
            assert isinstance(result, ParsedFile)
