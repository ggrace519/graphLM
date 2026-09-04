"""Tests for the Rust language pack (``graphlm[rust]``)."""

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
from graphlm.parsers import rust as rs
from graphlm.scanner import FileFragment, scan_project

LIB = "src/lib.rs"
FOO = "src/foo.rs"
BAR = "src/bar.rs"
NESTED = "src/nested/mod.rs"
DEEP = "src/nested/deep.rs"

EXPECTED_RUST_PROJECT_EDGES = {
    (LIB, FOO, "include"),
    (LIB, BAR, "include"),
    (LIB, NESTED, "include"),
    (LIB, FOO, "import"),
    (FOO, BAR, "import"),
    (FOO, DEEP, "import"),
    (BAR, FOO, "import"),
    (NESTED, DEEP, "include"),
    (NESTED, FOO, "import"),
    (DEEP, FOO, "import"),
}


def _rust_extra_installed() -> bool:
    return importlib.util.find_spec("tree_sitter_rust") is not None


class TestRustLayoutHelpers:
    def test_source_roots_grammar_free(self):
        assert rs._source_roots({"src/lib.rs", "src/foo.rs"}) == ("",)

    def test_owning_crate_prefers_lib(self):
        known = {"src/lib.rs", "src/main.rs", "src/foo.rs"}
        assert rs._owning_crate("src/foo.rs", known) == "src/lib.rs"
        assert rs._owning_crate("src/lib.rs", known) == "src/lib.rs"
        assert rs._owning_crate("src/main.rs", known) == "src/main.rs"

    def test_module_path_of(self):
        assert rs._module_path_of("src/lib.rs", "src/lib.rs") == ()
        assert rs._module_path_of("src/foo.rs", "src/lib.rs") == ("foo",)
        assert rs._module_path_of("src/nested/mod.rs", "src/lib.rs") == ("nested",)
        assert rs._module_path_of("src/nested/deep.rs", "src/lib.rs") == (
            "nested",
            "deep",
        )

    def test_mod_candidates_from_crate_root_and_file_module(self):
        assert rs._mod_candidates("src/lib.rs", "foo") == (
            "src/foo.rs",
            "src/foo/mod.rs",
        )
        assert rs._mod_candidates("src/foo.rs", "child") == (
            "src/foo/child.rs",
            "src/foo/child/mod.rs",
        )
        assert rs._mod_candidates("src/nested/mod.rs", "deep") == (
            "src/nested/deep.rs",
            "src/nested/deep/mod.rs",
        )

    def test_use_path_item_vs_submodule(self):
        modules = {
            (): "src/lib.rs",
            ("foo",): "src/foo.rs",
            ("foo", "bar"): "src/foo/bar.rs",
        }
        # item in foo → foo.rs
        assert (
            rs._resolve_use_path(("crate", "foo", "helper"), (), modules)
            == "src/foo.rs"
        )
        # submodule foo::bar → foo/bar.rs
        assert (
            rs._resolve_use_path(("crate", "foo", "bar"), (), modules)
            == "src/foo/bar.rs"
        )


@pytest.mark.skipif(
    _rust_extra_installed(),
    reason="rust extra is installed; extra-absent path is the other CI job",
)
class TestRustExtraAbsent:
    def test_two_rs_files_one_warning_python_intact(
        self, tmp_path, caplog, monkeypatch
    ):
        from graphlm.parsers import base as parser_base

        parser_base._backend._language_cache.clear()
        monkeypatch.setattr(parser_base, "_WARNED_GRAMMARS", set())

        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "a.py").write_text("x = 1\n")
        (tmp_path / "main.py").write_text("from pkg.a import x\n")
        (tmp_path / "lib.rs").write_text("mod foo;\n")
        (tmp_path / "foo.rs").write_text("pub fn x() {}\n")

        python_frags = [
            FileFragment("pkg/__init__.py", "", 1),
            FileFragment("pkg/a.py", "x = 1\n", 1),
            FileFragment("main.py", "from pkg.a import x\n", 1),
        ]
        rust_frags = [
            FileFragment("lib.rs", "mod foo;\n", 1),
            FileFragment("foo.rs", "pub fn x() {}\n", 1),
        ]
        python_only = build_dependency_graph(python_frags, project_dir=tmp_path)
        with caplog.at_level(logging.WARNING, logger=parser_base.logger.name):
            edges = build_dependency_graph(
                python_frags + rust_frags, project_dir=tmp_path
            )
        assert edges is not None
        assert edges == python_only
        rust_warnings = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "rust" in r.getMessage()
        ]
        assert len(rust_warnings) == 1


@pytest.mark.skipif(
    not _rust_extra_installed(),
    reason="graphlm[rust] extra not installed",
)
class TestRustPack:
    def test_exact_edge_set_on_rust_project(self, rust_project):
        scan = scan_project(rust_project, include_tests=True)
        edges = build_dependency_graph(scan.file_fragments, project_dir=rust_project)
        got = {(e.from_path, e.to_path, e.kind) for e in edges}
        assert got == EXPECTED_RUST_PROJECT_EDGES

    def test_external_crate_produces_no_edge(self, rust_project):
        scan = scan_project(rust_project, include_tests=True)
        edges = build_dependency_graph(scan.file_fragments, project_dir=rust_project)
        assert not any("serde" in e.to_path for e in edges)

    def test_foo_bar_cycle(self, rust_project):
        scan = scan_project(rust_project, include_tests=True)
        edges = build_dependency_graph(scan.file_fragments, project_dir=rust_project)
        cycles = detect_import_cycles(edges)
        members = {frozenset(c) for c in cycles}
        # foo ↔ bar and foo ↔ nested/deep collapse to one SCC.
        assert frozenset({FOO, BAR, DEEP}) in members

    def test_parse_file_returns_mod_and_use(self, rust_project):
        result = parse_file(rust_project / LIB)
        assert result is not None
        kinds = {e.kind for e in result.imports}
        assert "include" in kinds
        assert "import" in kinds
        specs = {e.to_path for e in result.imports}
        assert "foo.rs" in specs
        assert "crate/foo/helper.rs" in specs  # placeholder, not resolved

    def test_inline_mod_marks_partial(self, tmp_path):
        (tmp_path / "lib.rs").write_text("mod inline { pub fn x() {} }\n")
        frags = [FileFragment("lib.rs", "mod inline { pub fn x() {} }\n", 1)]
        partial: set[str] = set()
        edges = build_dependency_graph(
            frags, project_dir=tmp_path, partial_languages=partial
        )
        assert edges == []
        assert "rust" in partial

    def test_path_attr_mod_marks_partial(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "lib.rs").write_text('#[path = "elsewhere.rs"]\nmod relocated;\n')
        (src / "elsewhere.rs").write_text("pub fn x() {}\n")
        frags = [
            FileFragment(
                "src/lib.rs", '#[path = "elsewhere.rs"]\nmod relocated;\n', 2
            ),
            FileFragment("src/elsewhere.rs", "pub fn x() {}\n", 1),
        ]
        partial: set[str] = set()
        edges = build_dependency_graph(
            frags, project_dir=tmp_path, partial_languages=partial
        )
        assert not any(e.to_path.endswith("elsewhere.rs") for e in edges)
        assert "rust" in partial

    def test_use_glob_resolves_to_module_file(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "lib.rs").write_text("mod foo;\nuse crate::foo::*;\n")
        (src / "foo.rs").write_text("pub fn x() {}\n")
        frags = [
            FileFragment("src/lib.rs", "mod foo;\nuse crate::foo::*;\n", 2),
            FileFragment("src/foo.rs", "pub fn x() {}\n", 1),
        ]
        edges = build_dependency_graph(frags, project_dir=tmp_path)
        kinds = {(e.to_path, e.kind) for e in edges if e.from_path == "src/lib.rs"}
        assert ("src/foo.rs", "include") in kinds
        assert ("src/foo.rs", "import") in kinds

    def test_no_policy_drop_means_not_partial(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "lib.rs").write_text("mod foo;\n")
        (src / "foo.rs").write_text("pub fn x() {}\n")
        frags = [
            FileFragment("src/lib.rs", "mod foo;\n", 1),
            FileFragment("src/foo.rs", "pub fn x() {}\n", 1),
        ]
        partial: set[str] = set()
        edges = build_dependency_graph(
            frags, project_dir=tmp_path, partial_languages=partial
        )
        assert edges
        assert partial == set()
