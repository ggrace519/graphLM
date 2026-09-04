"""Tests for the C/C++ language pack (``graphlm[cpp]``).

Enabled-path tests skip when the extra is not installed (the default CI job).
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

import pytest

from graphlm.parser import (
    build_dependency_graph,
    detect_import_cycles,
    parse_file,
)
from graphlm.scanner import FileFragment, scan_project


def _cpp_extra_installed() -> bool:
    return (
        importlib.util.find_spec("tree_sitter_c") is not None
        and importlib.util.find_spec("tree_sitter_cpp") is not None
    )


MAIN = "src/main.c"
FOO_H = "src/foo.h"
FOO_C = "src/foo.c"
BAZ_H = "src/bar/baz.h"
BAZ_C = "src/bar/baz.c"
APP = "src/app.cpp"
QUX = "src/qux.hpp"
CA = "src/cycle_a.h"
CB = "src/cycle_b.h"

EXPECTED_CPP_PROJECT_EDGES = {
    (MAIN, FOO_H, "include"),
    (MAIN, BAZ_H, "include"),
    (FOO_C, FOO_H, "include"),
    (BAZ_C, BAZ_H, "include"),
    (APP, FOO_H, "include"),
    (APP, QUX, "include"),
    (CA, CB, "include"),
    (CB, CA, "include"),
}


@pytest.mark.skipif(
    _cpp_extra_installed(),
    reason="cpp extra is installed; extra-absent path is the other CI job",
)
class TestCppExtraAbsent:
    def test_c_and_cpp_files_one_warning_each_python_intact(
        self, tmp_path, caplog, monkeypatch
    ):
        from graphlm.parsers import base as parser_base

        parser_base._backend._language_cache.clear()
        monkeypatch.setattr(parser_base, "_WARNED_GRAMMARS", set())

        (tmp_path / "main.py").write_text("x = 1\n")
        (tmp_path / "a.c").write_text('#include "b.h"\n')
        (tmp_path / "b.h").write_text("int b;\n")
        (tmp_path / "a.cpp").write_text('#include "b.hpp"\n')
        (tmp_path / "b.hpp").write_text("int b;\n")

        python_frags = [FileFragment("main.py", "x = 1\n", 1)]
        other = [
            FileFragment("a.c", '#include "b.h"\n', 1),
            FileFragment("b.h", "int b;\n", 1),
            FileFragment("a.cpp", '#include "b.hpp"\n', 1),
            FileFragment("b.hpp", "int b;\n", 1),
        ]
        python_only = build_dependency_graph(python_frags, project_dir=tmp_path)
        with caplog.at_level(logging.WARNING, logger=parser_base.logger.name):
            edges = build_dependency_graph(
                python_frags + other, project_dir=tmp_path
            )
        assert edges is not None
        assert edges == python_only
        msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("for c " in m for m in msgs)
        assert any("for cpp " in m for m in msgs)


@pytest.mark.skipif(
    not _cpp_extra_installed(),
    reason="graphlm[cpp] extra not installed",
)
class TestCppPack:
    def test_exact_edge_set_on_cpp_project(self, cpp_project):
        scan = scan_project(cpp_project, include_tests=True)
        edges = build_dependency_graph(scan.file_fragments, project_dir=cpp_project)
        got = {(e.from_path, e.to_path, e.kind) for e in edges}
        assert got == EXPECTED_CPP_PROJECT_EDGES

    def test_system_headers_not_edges(self, cpp_project):
        scan = scan_project(cpp_project, include_tests=True)
        edges = build_dependency_graph(scan.file_fragments, project_dir=cpp_project)
        assert not any("stdio" in e.to_path or "vector" in e.to_path for e in edges)

    def test_parse_file_quoted_include(self, cpp_project):
        result = parse_file(cpp_project / MAIN)
        assert result is not None
        specs = {e.to_path for e in result.imports}
        assert "foo.h" in specs
        assert "bar/baz.h" in specs
        assert not any("stdio" in s for s in specs)

    def test_header_cycle(self, cpp_project):
        scan = scan_project(cpp_project, include_tests=True)
        edges = build_dependency_graph(scan.file_fragments, project_dir=cpp_project)
        cycles = detect_import_cycles(edges)
        members = {frozenset(c) for c in cycles}
        assert frozenset({CA, CB}) in members

    def test_macro_include_marks_partial(self, tmp_path):
        (tmp_path / "a.c").write_text("#include FOO\n")
        (tmp_path / "foo.h").write_text("int x;\n")
        frags = [
            FileFragment("a.c", "#include FOO\n", 1),
            FileFragment("foo.h", "int x;\n", 1),
        ]
        partial: set[str] = set()
        edges = build_dependency_graph(
            frags, project_dir=tmp_path, partial_languages=partial
        )
        assert edges == []
        assert "c" in partial
