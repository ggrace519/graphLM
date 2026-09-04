"""Tests for the Go language pack (``graphlm[go]``)."""

from __future__ import annotations

import importlib.util
import logging

import pytest

from graphlm.parser import (
    build_dependency_graph,
    detect_import_cycles,
    parse_file,
)
from graphlm.scanner import FileFragment, scan_project


def _go_extra_installed() -> bool:
    return importlib.util.find_spec("tree_sitter_go") is not None


MAIN = "main.go"
PKG = "pkg/pkg.go"
FOO = "foo/foo.go"
REL = "rel/rel.go"
TOO_A = "toomany/a.go"
TOO_B = "toomany/b.go"

EXPECTED_GO_PROJECT_EDGES = {
    (MAIN, PKG, "import"),
    (MAIN, REL, "import"),
    (PKG, FOO, "import"),
    (FOO, PKG, "import"),
}


@pytest.mark.skipif(
    _go_extra_installed(),
    reason="go extra is installed; extra-absent path is the other CI job",
)
class TestGoExtraAbsent:
    def test_two_go_files_one_warning_python_intact(self, tmp_path, caplog, monkeypatch):
        from graphlm.parsers import base as parser_base

        parser_base._backend._language_cache.clear()
        monkeypatch.setattr(parser_base, "_WARNED_GRAMMARS", set())

        (tmp_path / "main.py").write_text("x = 1\n")
        (tmp_path / "a.go").write_text('package a\nimport "./b"\n')
        (tmp_path / "b.go").write_text("package b\n")

        python_frags = [FileFragment("main.py", "x = 1\n", 1)]
        go_frags = [
            FileFragment("a.go", 'package a\nimport "./b"\n', 1),
            FileFragment("b.go", "package b\n", 1),
        ]
        python_only = build_dependency_graph(python_frags, project_dir=tmp_path)
        with caplog.at_level(logging.WARNING, logger=parser_base.logger.name):
            edges = build_dependency_graph(
                python_frags + go_frags, project_dir=tmp_path
            )
        assert edges is not None
        assert edges == python_only
        go_warnings = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "for go " in r.getMessage()
        ]
        assert len(go_warnings) == 1


@pytest.mark.skipif(
    not _go_extra_installed(),
    reason="graphlm[go] extra not installed",
)
class TestGoPack:
    def test_exact_edge_set_on_go_project(self, go_project):
        scan = scan_project(go_project, include_tests=True)
        edges = build_dependency_graph(scan.file_fragments, project_dir=go_project)
        got = {(e.from_path, e.to_path, e.kind) for e in edges}
        assert got == EXPECTED_GO_PROJECT_EDGES

    def test_multifile_package_marks_partial(self, go_project):
        scan = scan_project(go_project, include_tests=True)
        partial: set[str] = set()
        edges = build_dependency_graph(
            scan.file_fragments,
            project_dir=go_project,
            partial_languages=partial,
        )
        assert not any(e.to_path in {TOO_A, TOO_B} for e in edges)
        assert "go" in partial

    def test_stdlib_not_an_edge(self, go_project):
        scan = scan_project(go_project, include_tests=True)
        edges = build_dependency_graph(scan.file_fragments, project_dir=go_project)
        assert not any("fmt" in e.to_path for e in edges)

    def test_parse_file_import_paths(self, go_project):
        result = parse_file(go_project / MAIN)
        assert result is not None
        specs = {e.to_path for e in result.imports}
        assert "fmt" in specs
        assert "example.com/hello/pkg" in specs
        assert "./rel" in specs

    def test_pkg_foo_cycle(self, go_project):
        scan = scan_project(go_project, include_tests=True)
        edges = build_dependency_graph(scan.file_fragments, project_dir=go_project)
        cycles = detect_import_cycles(edges)
        members = {frozenset(c) for c in cycles}
        assert frozenset({PKG, FOO}) in members
