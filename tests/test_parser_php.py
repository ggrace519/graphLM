"""Tests for the PHP language pack (``graphlm[php]``)."""

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


def _php_extra_installed() -> bool:
    return importlib.util.find_spec("tree_sitter_php") is not None


INDEX = "src/App/index.php"
USER = "src/App/Models/User.php"
SVC = "src/App/Services/UserService.php"
BOOT = "src/App/bootstrap.php"
REL = "src/App/rel.php"

EXPECTED_PHP_PROJECT_EDGES = {
    (INDEX, USER, "import"),
    (INDEX, SVC, "import"),
    (INDEX, BOOT, "include"),
    (INDEX, REL, "include"),
    (USER, SVC, "import"),
    (SVC, USER, "import"),
}


@pytest.mark.skipif(
    _php_extra_installed(),
    reason="php extra is installed; extra-absent path is the other CI job",
)
class TestPhpExtraAbsent:
    def test_two_php_files_one_warning_python_intact(self, tmp_path, caplog, monkeypatch):
        from graphlm.parsers import base as parser_base

        parser_base._backend._language_cache.clear()
        monkeypatch.setattr(parser_base, "_WARNED_GRAMMARS", set())

        (tmp_path / "main.py").write_text("x = 1\n")
        (tmp_path / "a.php").write_text("<?php require 'b.php';\n")
        (tmp_path / "b.php").write_text("<?php\n")

        python_frags = [FileFragment("main.py", "x = 1\n", 1)]
        php_frags = [
            FileFragment("a.php", "<?php require 'b.php';\n", 1),
            FileFragment("b.php", "<?php\n", 1),
        ]
        python_only = build_dependency_graph(python_frags, project_dir=tmp_path)
        with caplog.at_level(logging.WARNING, logger=parser_base.logger.name):
            edges = build_dependency_graph(
                python_frags + php_frags, project_dir=tmp_path
            )
        assert edges is not None
        assert edges == python_only
        php_warnings = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "for php " in r.getMessage()
        ]
        assert len(php_warnings) == 1


@pytest.mark.skipif(
    not _php_extra_installed(),
    reason="graphlm[php] extra not installed",
)
class TestPhpPack:
    def test_exact_edge_set_on_php_project(self, php_project):
        scan = scan_project(php_project, include_tests=True)
        edges = build_dependency_graph(scan.file_fragments, project_dir=php_project)
        got = {(e.from_path, e.to_path, e.kind) for e in edges}
        assert got == EXPECTED_PHP_PROJECT_EDGES

    def test_missing_vendor_autoload_not_an_edge(self, php_project):
        scan = scan_project(php_project, include_tests=True)
        edges = build_dependency_graph(scan.file_fragments, project_dir=php_project)
        assert not any("autoload" in e.to_path for e in edges)

    def test_parse_file_use_and_require(self, php_project):
        result = parse_file(php_project / INDEX)
        assert result is not None
        specs = {(e.to_path, e.kind) for e in result.imports}
        assert ("App/Models/User.php", "import") in specs
        assert ("bootstrap.php", "include") in specs

    def test_user_service_cycle(self, php_project):
        scan = scan_project(php_project, include_tests=True)
        edges = build_dependency_graph(scan.file_fragments, project_dir=php_project)
        cycles = detect_import_cycles(edges)
        members = {frozenset(c) for c in cycles}
        assert frozenset({USER, SVC}) in members

    def test_concat_require_marks_partial(self, tmp_path):
        (tmp_path / "a.php").write_text('<?php require_once __DIR__ . "/b.php";\n')
        (tmp_path / "b.php").write_text("<?php\n")
        frags = [
            FileFragment("a.php", '<?php require_once __DIR__ . "/b.php";\n', 1),
            FileFragment("b.php", "<?php\n", 1),
        ]
        partial: set[str] = set()
        edges = build_dependency_graph(
            frags, project_dir=tmp_path, partial_languages=partial
        )
        assert edges == []
        assert "php" in partial
