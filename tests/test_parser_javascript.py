"""Tests for the JS/TS language pack (``graphlm[js]``).

Enabled-path tests skip when the extra is not installed (the default CI job).
Degradation when the extra is genuinely absent is covered here too, skipped
the other way so the extra-installed CI job still has a dedicated mixed-language
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
from graphlm.parsers import javascript as js
from graphlm.scanner import FileFragment, scan_project

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _js_extra_installed() -> bool:
    return (
        importlib.util.find_spec("tree_sitter_javascript") is not None
        and importlib.util.find_spec("tree_sitter_typescript") is not None
    )


EXPECTED_TS_PROJECT_EDGES = {
    ("src/foo.ts", "src/bar.ts", "import"),
    ("src/bar.ts", "src/foo.ts", "import"),
    ("src/index.ts", "src/foo.ts", "import"),
    ("src/index.ts", "src/Button.tsx", "import"),
    ("src/Button.tsx", "src/foo.ts", "import"),
    ("src/util/index.ts", "src/util/helper.ts", "import"),
    ("src/nested/deep.ts", "src/util/index.ts", "import"),
    ("src/nested/deep.ts", "src/foo.ts", "import"),
    ("src/nested/legacy.js", "src/foo.ts", "require"),
    ("src/nested/legacy.js", "src/bar.ts", "import"),
}


class TestJsSourceRootsAreGrammarFree:
    def test_source_roots_does_not_import_grammar(self):
        # Must not touch the grammar so a missing extra cannot poison the run
        # (Phase 1 handoff item 3).
        assert js._source_roots({"src/foo.ts", "src/bar.ts"}) == ("",)


class TestJsResolutionHelpers:
    def test_relative_join_and_escape(self):
        assert js._normalize_relative("src/nested/deep.ts", "../foo") == "src/foo"
        assert js._normalize_relative("src/index.ts", "./foo") == "src/foo"
        assert js._normalize_relative("src/index.ts", "../../outside") is None
        assert js._normalize_relative("src/index.ts", "react") is None

    def test_candidates_probe_order(self):
        c = js._candidates("src/foo", "src/a.ts")
        assert c[0] == "src/foo"
        assert "src/foo.ts" in c
        assert "src/foo/index.ts" in c
        assert c.index("src/foo.ts") < c.index("src/foo/index.ts")
        # Importer language: JS prefers .js siblings, TS prefers .ts.
        js_c = js._candidates("src/foo", "src/a.js")
        assert js_c.index("src/foo.js") < js_c.index("src/foo.ts")
        ts_c = js._candidates("src/foo", "src/a.ts")
        assert ts_c.index("src/foo.ts") < ts_c.index("src/foo.js")

    def test_bare_import_marks_not_relative(self):
        imp = js._js_import("react", "import")
        assert imp.is_relative is False
        rel = js._js_import("./foo", "import")
        assert rel.is_relative is True


@pytest.mark.skipif(
    _js_extra_installed(),
    reason="js extra is installed; extra-absent path is the other CI job",
)
class TestJsExtraAbsent:
    def test_two_ts_files_one_warning_python_intact(self, tmp_path, caplog, monkeypatch):
        from graphlm.parsers import base as parser_base

        parser_base._backend._language_cache.clear()
        monkeypatch.setattr(parser_base, "_WARNED_GRAMMARS", set())

        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "a.py").write_text("x = 1\n")
        (tmp_path / "main.py").write_text("from pkg.a import x\n")
        (tmp_path / "app.ts").write_text('import { x } from "./util";\n')
        (tmp_path / "util.ts").write_text("export const x = 1;\n")

        python_frags = [
            FileFragment("pkg/__init__.py", "", 1),
            FileFragment("pkg/a.py", "x = 1\n", 1),
            FileFragment("main.py", "from pkg.a import x\n", 1),
        ]
        ts_frags = [
            FileFragment("app.ts", 'import { x } from "./util";\n', 1),
            FileFragment("util.ts", "export const x = 1;\n", 1),
        ]
        python_only = build_dependency_graph(python_frags, project_dir=tmp_path)
        with caplog.at_level(logging.WARNING, logger=parser_base.logger.name):
            edges = build_dependency_graph(
                python_frags + ts_frags, project_dir=tmp_path
            )
        assert edges is not None
        assert edges == python_only
        ts_warnings = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "typescript" in r.getMessage()
        ]
        assert len(ts_warnings) == 1

    def test_parse_file_ts_returns_empty_parsed_file(self, tmp_path, monkeypatch):
        from graphlm.parsers import base as parser_base

        monkeypatch.setattr(parser_base, "_WARNED_GRAMMARS", set())
        src = tmp_path / "app.ts"
        src.write_text('import { x } from "./util";\n')
        result = parse_file(src)
        assert result is not None
        assert result.imports == []


@pytest.mark.skipif(
    not _js_extra_installed(),
    reason="graphlm[js] extra not installed",
)
class TestJsTsPack:
    def test_exact_edge_set_on_ts_project(self, ts_project):
        scan = scan_project(ts_project, include_tests=True)
        edges = build_dependency_graph(scan.file_fragments, project_dir=ts_project)
        got = {(e.from_path, e.to_path, e.kind) for e in edges}
        assert got == EXPECTED_TS_PROJECT_EDGES

    def test_bare_import_produces_no_edge(self, ts_project):
        scan = scan_project(ts_project, include_tests=True)
        edges = build_dependency_graph(scan.file_fragments, project_dir=ts_project)
        assert not any(e.to_path == "react" or "react" in e.to_path for e in edges)

    def test_bare_import_marks_language_partial(self, ts_project):
        scan = scan_project(ts_project, include_tests=True)
        partial: set[str] = set()
        build_dependency_graph(
            scan.file_fragments,
            project_dir=ts_project,
            partial_languages=partial,
        )
        assert "typescript" in partial

    def test_parse_file_returns_real_imports(self, ts_project):
        result = parse_file(ts_project / "src" / "foo.ts")
        assert result is not None
        specs = {e.to_path for e in result.imports}
        assert "./bar" in specs
        assert "react" in specs  # placeholder; resolution drops it

    def test_parse_file_tsx_with_jsx(self, ts_project):
        result = parse_file(ts_project / "src" / "Button.tsx")
        assert result is not None
        assert any(e.to_path == "./foo" for e in result.imports)

    def test_require_kind_on_cjs(self, ts_project):
        result = parse_file(ts_project / "src" / "nested" / "legacy.js")
        assert result is not None
        kinds = {e.to_path: e.kind for e in result.imports}
        assert kinds.get("../foo") == "require"
        assert kinds.get("../bar") == "import"

    def test_foo_bar_cycle(self, ts_project):
        scan = scan_project(ts_project, include_tests=True)
        edges = build_dependency_graph(scan.file_fragments, project_dir=ts_project)
        cycles = detect_import_cycles(edges)
        members = {frozenset(c) for c in cycles}
        assert frozenset({"src/foo.ts", "src/bar.ts"}) in members

    def test_index_barrel_from_directory_specifier(self, ts_project):
        scan = scan_project(ts_project, include_tests=True)
        edges = build_dependency_graph(scan.file_fragments, project_dir=ts_project)
        assert any(
            e.from_path == "src/nested/deep.ts" and e.to_path == "src/util/index.ts"
            for e in edges
        )

    def test_extension_on_specifier_hits_exact_file(self, tmp_path):
        (tmp_path / "a.ts").write_text('import { b } from "./b.ts";\n')
        (tmp_path / "b.ts").write_text("export const b = 1;\n")
        frags = [
            FileFragment("a.ts", 'import { b } from "./b.ts";\n', 1),
            FileFragment("b.ts", "export const b = 1;\n", 1),
        ]
        edges = build_dependency_graph(frags, project_dir=tmp_path)
        assert {(e.from_path, e.to_path, e.kind) for e in edges} == {
            ("a.ts", "b.ts", "import")
        }

    def test_ts_import_equals_require(self, tmp_path):
        (tmp_path / "a.ts").write_text('import foo = require("./b");\n')
        (tmp_path / "b.ts").write_text("export const foo = 1;\n")
        frags = [
            FileFragment("a.ts", 'import foo = require("./b");\n', 1),
            FileFragment("b.ts", "export const foo = 1;\n", 1),
        ]
        edges = build_dependency_graph(frags, project_dir=tmp_path)
        assert {(e.from_path, e.to_path, e.kind) for e in edges} == {
            ("a.ts", "b.ts", "require")
        }

    def test_dynamic_import_template_with_substitution_dropped(self, tmp_path):
        (tmp_path / "a.ts").write_text("const m = import(`./b/${x}`);\n")
        (tmp_path / "b.ts").write_text("export const x = 1;\n")
        frags = [
            FileFragment("a.ts", "const m = import(`./b/${x}`);\n", 1),
            FileFragment("b.ts", "export const x = 1;\n", 1),
        ]
        edges = build_dependency_graph(frags, project_dir=tmp_path)
        assert edges == []

    def test_js_importer_prefers_js_sibling_over_ts(self, tmp_path):
        (tmp_path / "a.js").write_text('const b = require("./b");\n')
        (tmp_path / "b.js").write_text("module.exports = 1;\n")
        (tmp_path / "b.ts").write_text("export const b = 1;\n")
        frags = [
            FileFragment("a.js", 'const b = require("./b");\n', 1),
            FileFragment("b.js", "module.exports = 1;\n", 1),
            FileFragment("b.ts", "export const b = 1;\n", 1),
        ]
        edges = build_dependency_graph(frags, project_dir=tmp_path)
        assert {(e.from_path, e.to_path, e.kind) for e in edges} == {
            ("a.js", "b.js", "require")
        }

    def test_ts_importer_prefers_ts_sibling_over_js(self, tmp_path):
        (tmp_path / "a.ts").write_text('import { b } from "./b";\n')
        (tmp_path / "b.js").write_text("export const b = 1;\n")
        (tmp_path / "b.ts").write_text("export const b = 1;\n")
        frags = [
            FileFragment("a.ts", 'import { b } from "./b";\n', 1),
            FileFragment("b.js", "export const b = 1;\n", 1),
            FileFragment("b.ts", "export const b = 1;\n", 1),
        ]
        edges = build_dependency_graph(frags, project_dir=tmp_path)
        assert {(e.from_path, e.to_path, e.kind) for e in edges} == {
            ("a.ts", "b.ts", "import")
        }

    def test_relative_only_project_is_not_partial(self, tmp_path):
        (tmp_path / "a.ts").write_text('import { b } from "./b";\n')
        (tmp_path / "b.ts").write_text("export const b = 1;\n")
        frags = [
            FileFragment("a.ts", 'import { b } from "./b";\n', 1),
            FileFragment("b.ts", "export const b = 1;\n", 1),
        ]
        partial: set[str] = set()
        edges = build_dependency_graph(
            frags, project_dir=tmp_path, partial_languages=partial
        )
        assert edges
        assert partial == set()
