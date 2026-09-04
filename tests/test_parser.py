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

    def test_java(self):
        assert detect_language(Path("Foo.java")) == "java"
        assert detect_language(Path("FOO.JAVA")) == "java"

    def test_rust(self):
        assert detect_language(Path("lib.rs")) == "rust"
        assert detect_language(Path("FOO.RS")) == "rust"

    def test_csharp(self):
        assert detect_language(Path("Program.cs")) == "csharp"
        assert detect_language(Path("FOO.CS")) == "csharp"

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

        from graphlm.scanner import scan_project

        scan = scan_project(large_project, include_tests=False)
        edges = build_dependency_graph(scan.file_fragments, project_dir=large_project)
        main_targets = {e.to_path for e in edges if e.from_path == "app/main.py"}
        assert "app/routes/users.py" in main_targets
        assert "app/routes/items.py" in main_targets
        assert "app/services/auth.py" in main_targets
        assert "app/routes.py" not in main_targets
        assert "fastapi.py" not in main_targets

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
        targets = {e.to_path for e in edges}

        assert ("app/routes/items.py", "app/models/item.py") in edge_set
        assert ("app/routes/items.py", "app/services/item_service.py") in edge_set
        assert ("app/services/user_service.py", "app/services/auth.py") in edge_set
        assert ("app/main.py", "app/routes/users.py") in edge_set
        assert ("app/main.py", "app/routes/items.py") in edge_set
        assert ("app/main.py", "app/services/auth.py") in edge_set
        assert "app/routes.py" not in targets
        assert "fastapi.py" not in targets
        assert "os.py" not in targets

    def test_stdlib_and_future_produce_zero_edges(self, tmp_path):
        from graphlm.scanner import FileFragment

        src = tmp_path / "mod.py"
        src.write_text(
            "from __future__ import annotations\n"
            "import os\n"
            "import json\n"
            "from json import dumps\n"
        )
        frag = FileFragment("mod.py", src.read_text(), 1)
        edges = build_dependency_graph([frag], project_dir=tmp_path)
        assert edges == []

    def test_relative_imports_resolve(self, tmp_path):
        from graphlm.scanner import scan_project

        app = tmp_path / "app"
        (app / "models").mkdir(parents=True)
        (app / "services").mkdir(parents=True)
        (app / "__init__.py").write_text("")
        (app / "models" / "__init__.py").write_text("")
        (app / "models" / "user.py").write_text("class User:\n    pass\n")
        (app / "services" / "__init__.py").write_text("")
        (app / "services" / "auth.py").write_text("def hash_password(p): return p\n")
        (app / "services" / "user_service.py").write_text(
            "from ..models.user import User\n"
            "from .auth import hash_password\n"
            "from . import auth\n"
        )

        scan = scan_project(tmp_path)
        edges = build_dependency_graph(scan.file_fragments, project_dir=tmp_path)
        edge_set = {(e.from_path, e.to_path) for e in edges}
        assert ("app/services/user_service.py", "app/models/user.py") in edge_set
        assert ("app/services/user_service.py", "app/services/auth.py") in edge_set

    def test_src_layout_imports_resolve(self, tmp_path):
        # Regression for #19: a src-layout project (package under src/) imports by
        # package name (`from mypkg.core import X`), but the scanned file is at
        # src/mypkg/core.py. Edges must still resolve across the src/ root.
        src = tmp_path / "src" / "mypkg"
        (src / "core").mkdir(parents=True)
        (src / "__init__.py").write_text("")
        (src / "core" / "__init__.py").write_text("")
        (src / "core" / "engine.py").write_text("class Engine:\n    pass\n")
        (src / "app.py").write_text(
            "from mypkg.core.engine import Engine\n"
            "import mypkg.core\n"
        )

        from graphlm.scanner import scan_project

        scan = scan_project(tmp_path)
        edges = build_dependency_graph(scan.file_fragments, project_dir=tmp_path)
        edge_set = {(e.from_path, e.to_path) for e in edges}
        assert ("src/mypkg/app.py", "src/mypkg/core/engine.py") in edge_set
        assert ("src/mypkg/app.py", "src/mypkg/core/__init__.py") in edge_set

    def test_root_layout_unaffected_by_src_roots(self, tmp_path):
        # A root-layout project must resolve exactly as before — root "" is tried
        # first, so adding src-root support (#19) doesn't change it or add edges.
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "__init__.py").write_text("")
        (tmp_path / "pkg" / "a.py").write_text("x = 1\n")
        (tmp_path / "main.py").write_text("from pkg.a import x\n")

        from graphlm.scanner import scan_project

        scan = scan_project(tmp_path)
        edges = build_dependency_graph(scan.file_fragments, project_dir=tmp_path)
        edge_set = {(e.from_path, e.to_path) for e in edges}
        assert ("main.py", "pkg/a.py") in edge_set
        # No spurious src/-prefixed target.
        assert not any("src/" in e.to_path for e in edges)

    def test_from_import_prefers_submodule_then_package_fallback(self, tmp_path):
        from graphlm.scanner import scan_project

        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("foo = 1\n")
        (pkg / "sub.py").write_text("x = 1\n")
        (tmp_path / "main.py").write_text("from pkg import sub, foo\n")

        scan = scan_project(tmp_path)
        edges = build_dependency_graph(scan.file_fragments, project_dir=tmp_path)
        main_targets = [e.to_path for e in edges if e.from_path == "main.py"]
        assert main_targets.count("pkg/sub.py") == 1
        assert main_targets.count("pkg/__init__.py") == 1
        assert "pkg.py" not in main_targets

    def test_source_roots_derivation(self):
        from graphlm.parser import _source_roots

        known = {
            "src/pkg/__init__.py",  # src-layout -> "src/" root
            "src/pkg/mod.py",
            "top/__init__.py",  # top-level package -> NO extra root
            "tests/stub/requests/__init__.py",  # junk shadow -> must NOT be a root
            "README.md",
        }
        roots = _source_roots(known)
        assert "" in roots  # project root always present
        assert "src/" in roots  # conventional source root, accepted
        # A top-level package yields no extra root beyond "".
        assert "top/" not in roots
        # An arbitrary directory that merely contains an __init__.py is NOT a
        # source root — deriving it manufactured false third-party edges (#19).
        assert "tests/" not in roots
        assert "tests/stub/" not in roots

    def test_source_roots_rejects_non_conventional_shadow_root(self, tmp_path):
        # End-to-end: a stub package shadowing a third-party import under a
        # non-conventional directory must NOT create a false project edge (#19).
        (tmp_path / "app.py").write_text("import requests\n")
        stub = tmp_path / "tests" / "stub" / "requests"
        stub.mkdir(parents=True)
        (stub / "__init__.py").write_text("")

        from graphlm.scanner import scan_project

        scan = scan_project(tmp_path)
        edges = build_dependency_graph(scan.file_fragments, project_dir=tmp_path)
        # import requests is third-party — it must resolve to nothing, not the stub.
        assert edges == []

    def test_cyclic_project_includes_cycle_edges(self):
        from graphlm.scanner import scan_project

        project = FIXTURES_DIR / "cyclic_project"
        scan = scan_project(project, include_tests=True)
        edges = build_dependency_graph(scan.file_fragments, project_dir=project)
        edge_set = {(e.from_path, e.to_path) for e in edges}
        assert ("app/main.py", "app/routes.py") in edge_set
        assert ("app/routes.py", "app/services.py") in edge_set
        assert ("app/services.py", "app/main.py") in edge_set


class TestMissingGrammarDegrades:
    """A registered language whose grammar pack is not installed must degrade to
    zero edges for that language, never poison the run (Phase 0 never-escapes
    invariant). ``build_dependency_graph`` must keep returning a list (not None,
    which __init__.py reads as "AST off") and keep every other language's edges.
    """

    def test_missing_grammar_yields_zero_edges_and_does_not_poison_run(
        self, tmp_path, monkeypatch, caplog
    ):
        import logging

        from graphlm.parsers import base as parser_base
        from graphlm.scanner import FileFragment

        # A fake language must clear the SAME gates a real one does before its
        # grammar is ever loaded: detect_language reads EXT_TO_LANGUAGE, and the
        # dispatch skips any language with no registered resolver. Register it in
        # all three registries so a ".fake" fragment actually reaches
        # _get_language("fake"), whose grammar module is not importable.
        fake_lang = "fake"
        monkeypatch.setitem(parser_base.EXT_TO_LANGUAGE, ".fake", fake_lang)
        monkeypatch.setitem(
            parser_base._GRAMMARS,
            fake_lang,
            parser_base._GrammarSpec("tree_sitter_nonexistent_xyz", "language"),
        )

        # Resolver whose extraction really invokes the backend for "fake", so the
        # missing-grammar ImportError -> _GrammarUnavailable path is exercised
        # (not skipped by an early return).
        def _fake_imports_from_source(code, path):
            parser_base._backend.parse_source(code, fake_lang)  # -> _GrammarUnavailable
            return []  # pragma: no cover - never reached

        fake_resolver = parser_base._Resolver(
            parse_file=lambda code, path: parser_base.ParsedFile(),
            imports_from_source=_fake_imports_from_source,
            source_roots=lambda known: ("",),
            resolve=lambda imp, from_path, known, roots: [],
            edge_kind=lambda imp: "import",
        )
        monkeypatch.setitem(parser_base._RESOLVERS, fake_lang, fake_resolver)
        # The warn-once dedupe is module-level; keep the test isolated.
        monkeypatch.setattr(parser_base, "_WARNED_GRAMMARS", set())

        # A mixed-language tree: a real Python edge chain + a .fake file. The
        # .fake file must contribute nothing while the Python edges survive.
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "a.py").write_text("x = 1\n")
        (tmp_path / "main.py").write_text("from pkg.a import x\n")
        (tmp_path / "widget.fake").write_text("import whatever from './other'\n")
        (tmp_path / "gadget.fake").write_text("import other from './else'\n")

        frags = [
            FileFragment("pkg/__init__.py", "", 1),
            FileFragment("pkg/a.py", "x = 1\n", 1),
            FileFragment("main.py", "from pkg.a import x\n", 1),
            FileFragment("widget.fake", "import whatever from './other'\n", 1),
            FileFragment("gadget.fake", "import other from './else'\n", 1),
        ]

        # Python-only baseline (no .fake fragment).
        python_only = build_dependency_graph(frags[:3], project_dir=tmp_path)

        with caplog.at_level(logging.WARNING, logger=parser_base.logger.name):
            edges = build_dependency_graph(frags, project_dir=tmp_path)

        # Never None with ast on — a missing grammar is not "AST off".
        assert edges is not None
        # The .fake file contributed zero edges; the Python edges are intact.
        assert edges == python_only
        edge_set = {(e.from_path, e.to_path) for e in edges}
        assert ("main.py", "pkg/a.py") in edge_set
        assert not any(e.from_path.endswith(".fake") for e in edges)

        # Exactly one warning line for the missing grammar (dedupe held) even
        # though TWO fragments of that language were parsed — once-per-language,
        # not once-per-file.
        grammar_warnings = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and fake_lang in r.getMessage()
        ]
        assert len(grammar_warnings) == 1

    def test_mixed_python_and_ts_missing_js_grammar_keeps_python_edges(
        self, tmp_path, monkeypatch, caplog
    ):
        """Never-escapes invariant with teeth: two .ts files + Python, JS
        grammars uninstalled (or monkeypatched so). Python edges survive,
        ``deterministic_edges`` is a list, one warning for typescript.
        """
        import logging

        from graphlm.parsers import base as parser_base
        from graphlm.scanner import FileFragment

        missing = parser_base._GrammarSpec("tree_sitter_nonexistent_js", "language")
        monkeypatch.setitem(parser_base._GRAMMARS, "javascript", missing)
        monkeypatch.setitem(parser_base._GRAMMARS, "typescript", missing)
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
        assert ("main.py", "pkg/a.py") in {(e.from_path, e.to_path) for e in edges}
        assert not any(e.from_path.endswith(".ts") for e in edges)
        ts_warnings = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "typescript" in r.getMessage()
        ]
        assert len(ts_warnings) == 1

    def test_mixed_python_and_java_missing_java_grammar_keeps_python_edges(
        self, tmp_path, monkeypatch, caplog
    ):
        import logging

        from graphlm.parsers import base as parser_base
        from graphlm.scanner import FileFragment

        missing = parser_base._GrammarSpec("tree_sitter_nonexistent_java", "language")
        monkeypatch.setitem(parser_base._GRAMMARS, "java", missing)
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

    def test_mixed_python_and_rust_missing_rust_grammar_keeps_python_edges(
        self, tmp_path, monkeypatch, caplog
    ):
        import logging

        from graphlm.parsers import base as parser_base
        from graphlm.scanner import FileFragment

        missing = parser_base._GrammarSpec("tree_sitter_nonexistent_rust", "language")
        monkeypatch.setitem(parser_base._GRAMMARS, "rust", missing)
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


class TestGrammarSpecSelection:
    def test_tsx_uses_language_tsx_accessor(self):
        from graphlm.parsers.base import _spec_for

        assert _spec_for("typescript", ".tsx").accessor == "language_tsx"
        assert _spec_for("typescript", ".TSX").accessor == "language_tsx"

    def test_ts_uses_language_typescript_accessor(self):
        from graphlm.parsers.base import _spec_for

        assert _spec_for("typescript", ".ts").accessor == "language_typescript"
        assert _spec_for("typescript", "").accessor == "language_typescript"

    def test_javascript_ignores_suffix(self):
        from graphlm.parsers.base import _spec_for

        spec_js = _spec_for("javascript", ".js")
        spec_jsx = _spec_for("javascript", ".jsx")
        assert spec_js.accessor == spec_jsx.accessor == "language"
        assert spec_js.pip_module == "tree_sitter_javascript"

    def test_python_unchanged(self):
        from graphlm.parsers.base import _spec_for

        spec = _spec_for("python", ".py")
        assert spec.pip_module == "tree_sitter_python"
        assert spec.accessor == "language"

    def test_java(self):
        from graphlm.parsers.base import _spec_for

        spec = _spec_for("java", ".java")
        assert spec.pip_module == "tree_sitter_java"
        assert spec.accessor == "language"

    def test_rust(self):
        from graphlm.parsers.base import _spec_for

        spec = _spec_for("rust", ".rs")
        assert spec.pip_module == "tree_sitter_rust"
        assert spec.accessor == "language"


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
        main_edges = [e for e in edges if e.from_path == "app/main.py"]
        main_targets = {e.to_path for e in main_edges}
        assert "app/routes/users.py" in main_targets
        assert "app/routes/items.py" in main_targets
        assert "app/services/auth.py" in main_targets
        assert "app/routes.py" not in main_targets
        assert "fastapi.py" not in main_targets

    def test_all_py_files_parsed(self, large_project):
        py_files = list(large_project.rglob("*.py"))
        assert len(py_files) > 0
        for fpath in py_files:
            result = parse_file(fpath)
            assert result is not None
            assert isinstance(result, ParsedFile)
