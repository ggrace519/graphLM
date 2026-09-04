"""Tests for the C# language pack (``graphlm[csharp]``).

Enabled-path tests skip when the extra is not installed (the default CI job).
Degradation when the extra is genuinely absent is covered here too, skipped
the other way so the extra-installed job still has the mixed-language
monkeypatch in ``test_parser.py``.
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
from graphlm.parsers import csharp as cs
from graphlm.scanner import FileFragment, scan_project

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _csharp_extra_installed() -> bool:
    return importlib.util.find_spec("tree_sitter_c_sharp") is not None


PROG = "src/MyApp/Program.cs"
USER = "src/MyApp/Models/User.cs"
SVC = "src/MyApp/Services/UserService.cs"
UTIL = "src/MyApp/Helpers/Util.cs"
TOO_A = "src/MyApp/TooMany/A.cs"
TOO_B = "src/MyApp/TooMany/B.cs"

EXPECTED_CSHARP_PROJECT_EDGES = {
    (PROG, USER, "import"),
    (PROG, UTIL, "static"),
    (USER, SVC, "import"),
    (SVC, USER, "import"),
}


class TestCsharpSourceRootsAreGrammarFree:
    def test_src_prefix(self):
        known = {
            "src/MyApp/Program.cs",
            "src/MyApp/Models/User.cs",
            "README.md",
        }
        roots = cs._source_roots(known)
        assert roots[0] == ""
        assert "src/" in roots


class TestCsharpDirFiles:
    def test_unique_and_multi(self):
        known = {
            "src/MyApp/Models/User.cs",
            "src/MyApp/TooMany/A.cs",
            "src/MyApp/TooMany/B.cs",
        }
        roots = ("", "src/")
        assert cs._dir_cs_files("MyApp/Models", known, roots) == [
            "src/MyApp/Models/User.cs"
        ]
        assert set(cs._dir_cs_files("MyApp/TooMany", known, roots)) == {
            "src/MyApp/TooMany/A.cs",
            "src/MyApp/TooMany/B.cs",
        }


@pytest.mark.skipif(
    _csharp_extra_installed(),
    reason="csharp extra is installed; extra-absent path is the other CI job",
)
class TestCsharpExtraAbsent:
    def test_two_cs_files_one_warning_python_intact(self, tmp_path, caplog, monkeypatch):
        from graphlm.parsers import base as parser_base

        parser_base._backend._language_cache.clear()
        monkeypatch.setattr(parser_base, "_WARNED_GRAMMARS", set())

        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "a.py").write_text("x = 1\n")
        (tmp_path / "main.py").write_text("from pkg.a import x\n")
        (tmp_path / "A.cs").write_text("using B;\n")
        (tmp_path / "B.cs").write_text("class B {}\n")

        python_frags = [
            FileFragment("pkg/__init__.py", "", 1),
            FileFragment("pkg/a.py", "x = 1\n", 1),
            FileFragment("main.py", "from pkg.a import x\n", 1),
        ]
        cs_frags = [
            FileFragment("A.cs", "using B;\n", 1),
            FileFragment("B.cs", "class B {}\n", 1),
        ]
        python_only = build_dependency_graph(python_frags, project_dir=tmp_path)
        with caplog.at_level(logging.WARNING, logger=parser_base.logger.name):
            edges = build_dependency_graph(
                python_frags + cs_frags, project_dir=tmp_path
            )
        assert edges is not None
        assert edges == python_only
        cs_warnings = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "csharp" in r.getMessage()
        ]
        assert len(cs_warnings) == 1


@pytest.mark.skipif(
    not _csharp_extra_installed(),
    reason="graphlm[csharp] extra not installed",
)
class TestCsharpPack:
    def test_exact_edge_set_on_csharp_project(self, csharp_project):
        scan = scan_project(csharp_project, include_tests=True)
        edges = build_dependency_graph(scan.file_fragments, project_dir=csharp_project)
        got = {(e.from_path, e.to_path, e.kind) for e in edges}
        assert got == EXPECTED_CSHARP_PROJECT_EDGES

    def test_multifile_namespace_produces_no_edge_and_marks_partial(self, csharp_project):
        scan = scan_project(csharp_project, include_tests=True)
        partial: set[str] = set()
        edges = build_dependency_graph(
            scan.file_fragments,
            project_dir=csharp_project,
            partial_languages=partial,
        )
        assert not any(e.to_path in {TOO_A, TOO_B} for e in edges)
        assert "csharp" in partial

    def test_stdlib_not_an_edge(self, csharp_project):
        scan = scan_project(csharp_project, include_tests=True)
        edges = build_dependency_graph(scan.file_fragments, project_dir=csharp_project)
        assert not any("System" in e.to_path for e in edges)

    def test_parse_file_returns_real_usings(self, csharp_project):
        result = parse_file(csharp_project / PROG)
        assert result is not None
        specs = {(e.to_path, e.kind) for e in result.imports}
        assert ("MyApp/Models.cs", "import") in specs
        assert ("MyApp/Helpers/Util.cs", "static") in specs
        assert ("System.cs", "import") in specs

    def test_user_service_cycle(self, csharp_project):
        scan = scan_project(csharp_project, include_tests=True)
        edges = build_dependency_graph(scan.file_fragments, project_dir=csharp_project)
        cycles = detect_import_cycles(edges)
        members = {frozenset(c) for c in cycles}
        assert frozenset({USER, SVC}) in members

    def test_using_static_hits_type_file(self, tmp_path):
        src = tmp_path / "src/MyApp"
        src.mkdir(parents=True)
        (src / "A.cs").write_text("using static MyApp.B;\nclass A {}\n")
        (src / "B.cs").write_text("namespace MyApp; static class B {}\n")
        frags = [
            FileFragment("src/MyApp/A.cs", "using static MyApp.B;\n", 1),
            FileFragment("src/MyApp/B.cs", "namespace MyApp; static class B {}\n", 1),
        ]
        edges = build_dependency_graph(frags, project_dir=tmp_path)
        got = {(e.from_path, e.to_path, e.kind) for e in edges}
        assert ("src/MyApp/A.cs", "src/MyApp/B.cs", "static") in got
