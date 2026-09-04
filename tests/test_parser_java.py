"""Tests for the Java language pack (``graphlm[java]``).

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
from graphlm.parsers import java as jv
from graphlm.scanner import FileFragment, scan_project

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _java_extra_installed() -> bool:
    return importlib.util.find_spec("tree_sitter_java") is not None


APP = "src/main/java/com/acme/App.java"
USER = "src/main/java/com/acme/model/User.java"
SVC = "src/main/java/com/acme/service/UserService.java"
HELPERS = "src/main/java/com/acme/util/Helpers.java"
MORE = "src/main/java/com/acme/util/More.java"
APP_TEST = "src/test/java/com/acme/AppTest.java"

EXPECTED_JAVA_PROJECT_EDGES = {
    (APP, USER, "import"),
    (APP, SVC, "import"),
    (APP, HELPERS, "static"),
    (SVC, APP, "import"),
    (SVC, USER, "import"),
    (APP_TEST, APP, "import"),
}


class TestJavaSourceRootsAreGrammarFree:
    def test_maven_and_simple_layout(self):
        known = {
            "src/main/java/com/acme/App.java",
            "src/test/java/com/acme/AppTest.java",
            "src/com/other/Foo.java",
            "README.md",
        }
        roots = jv._source_roots(known)
        assert roots[0] == ""
        assert "src/main/java/" in roots
        assert "src/test/java/" in roots
        assert "src/" in roots

    def test_package_mismatch_does_not_invent_root(self):
        assert jv._root_from_package("src/main/java/wrong/Foo.java", "com.acme") == ""
        assert (
            jv._root_from_package("src/main/java/com/acme/Foo.java", "com.acme")
            == "src/main/java/"
        )


class TestJavaClassPaths:
    def test_nested_type_fallback(self):
        paths = jv._class_paths("com.acme.Foo.Bar")
        assert paths[0] == "com/acme/Foo/Bar.java"
        assert "com/acme/Foo.java" in paths

    def test_plain_type(self):
        assert jv._class_paths("com.acme.User") == ("com/acme/User.java",)


@pytest.mark.skipif(
    _java_extra_installed(),
    reason="java extra is installed; extra-absent path is the other CI job",
)
class TestJavaExtraAbsent:
    def test_two_java_files_one_warning_python_intact(self, tmp_path, caplog, monkeypatch):
        from graphlm.parsers import base as parser_base

        parser_base._backend._language_cache.clear()
        monkeypatch.setattr(parser_base, "_WARNED_GRAMMARS", set())

        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "a.py").write_text("x = 1\n")
        (tmp_path / "main.py").write_text("from pkg.a import x\n")
        (tmp_path / "App.java").write_text("import com.Foo;\n")
        (tmp_path / "Foo.java").write_text("class Foo {}\n")

        python_frags = [
            FileFragment("pkg/__init__.py", "", 1),
            FileFragment("pkg/a.py", "x = 1\n", 1),
            FileFragment("main.py", "from pkg.a import x\n", 1),
        ]
        java_frags = [
            FileFragment("App.java", "import com.Foo;\n", 1),
            FileFragment("Foo.java", "class Foo {}\n", 1),
        ]
        python_only = build_dependency_graph(python_frags, project_dir=tmp_path)
        with caplog.at_level(logging.WARNING, logger=parser_base.logger.name):
            edges = build_dependency_graph(
                python_frags + java_frags, project_dir=tmp_path
            )
        assert edges is not None
        assert edges == python_only
        java_warnings = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "java" in r.getMessage()
        ]
        assert len(java_warnings) == 1


@pytest.mark.skipif(
    not _java_extra_installed(),
    reason="graphlm[java] extra not installed",
)
class TestJavaPack:
    def test_exact_edge_set_on_java_project(self, java_project):
        scan = scan_project(java_project, include_tests=True)
        edges = build_dependency_graph(scan.file_fragments, project_dir=java_project)
        got = {(e.from_path, e.to_path, e.kind) for e in edges}
        assert got == EXPECTED_JAVA_PROJECT_EDGES

    def test_wildcard_produces_no_edge_and_marks_partial(self, java_project):
        scan = scan_project(java_project, include_tests=True)
        partial: set[str] = set()
        edges = build_dependency_graph(
            scan.file_fragments,
            project_dir=java_project,
            partial_languages=partial,
        )
        assert not any(e.to_path == MORE for e in edges)
        assert "java" in partial

    def test_stdlib_not_an_edge(self, java_project):
        scan = scan_project(java_project, include_tests=True)
        edges = build_dependency_graph(scan.file_fragments, project_dir=java_project)
        assert not any("java/util" in e.to_path for e in edges)

    def test_parse_file_returns_real_imports(self, java_project):
        result = parse_file(java_project / APP)
        assert result is not None
        specs = {(e.to_path, e.kind) for e in result.imports}
        assert ("com/acme/model/User.java", "import") in specs
        assert ("com/acme/util/Helpers.java", "static") in specs
        # Wildcard omitted from the placeholder view too.
        assert not any("util/*.java" in p or p[0].endswith("util.java") for p in specs)

    def test_app_userservice_cycle(self, java_project):
        scan = scan_project(java_project, include_tests=True)
        edges = build_dependency_graph(scan.file_fragments, project_dir=java_project)
        cycles = detect_import_cycles(edges)
        members = {frozenset(c) for c in cycles}
        assert frozenset({APP, SVC}) in members

    def test_test_root_resolves_into_main(self, java_project):
        scan = scan_project(java_project, include_tests=True)
        edges = build_dependency_graph(scan.file_fragments, project_dir=java_project)
        assert (APP_TEST, APP, "import") in {
            (e.from_path, e.to_path, e.kind) for e in edges
        }

    def test_static_star_resolves_to_class(self, tmp_path):
        src = tmp_path / "src/main/java/com/acme"
        src.mkdir(parents=True)
        (src / "A.java").write_text(
            "package com.acme;\nimport static com.acme.B.*;\nclass A {}\n"
        )
        (src / "B.java").write_text("package com.acme;\nclass B { static int x; }\n")
        frags = [
            FileFragment("src/main/java/com/acme/A.java", (src / "A.java").read_text(), 3),
            FileFragment("src/main/java/com/acme/B.java", (src / "B.java").read_text(), 2),
        ]
        edges = build_dependency_graph(frags, project_dir=tmp_path)
        assert {(e.from_path, e.to_path, e.kind) for e in edges} == {
            (
                "src/main/java/com/acme/A.java",
                "src/main/java/com/acme/B.java",
                "static",
            )
        }

    def test_nested_type_resolves_to_enclosing_class(self, tmp_path):
        src = tmp_path / "src/main/java/com/acme"
        src.mkdir(parents=True)
        (src / "A.java").write_text(
            "package com.acme;\nimport com.acme.Foo.Bar;\nclass A {}\n"
        )
        (src / "Foo.java").write_text(
            "package com.acme;\nclass Foo { static class Bar {} }\n"
        )
        frags = [
            FileFragment("src/main/java/com/acme/A.java", (src / "A.java").read_text(), 3),
            FileFragment("src/main/java/com/acme/Foo.java", (src / "Foo.java").read_text(), 2),
        ]
        edges = build_dependency_graph(frags, project_dir=tmp_path)
        assert {(e.from_path, e.to_path) for e in edges} == {
            ("src/main/java/com/acme/A.java", "src/main/java/com/acme/Foo.java")
        }

    def test_no_wildcard_means_not_partial(self, tmp_path):
        src = tmp_path / "src/main/java/com/acme"
        src.mkdir(parents=True)
        (src / "A.java").write_text(
            "package com.acme;\nimport com.acme.B;\nclass A {}\n"
        )
        (src / "B.java").write_text("package com.acme;\nclass B {}\n")
        frags = [
            FileFragment("src/main/java/com/acme/A.java", (src / "A.java").read_text(), 3),
            FileFragment("src/main/java/com/acme/B.java", (src / "B.java").read_text(), 2),
        ]
        partial: set[str] = set()
        edges = build_dependency_graph(
            frags, project_dir=tmp_path, partial_languages=partial
        )
        assert edges
        assert partial == set()
