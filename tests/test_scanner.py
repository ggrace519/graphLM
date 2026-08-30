"""Tests for the scanner module."""

from pathlib import Path

import pytest

from graphlm.scanner import (
    FileFragment,
    ScanResult,
    _is_binary,
    _is_sensitive_file,
    _redact_secrets,
    _should_exclude,
    estimate_tokens,
    scan_project,
)


class TestEstimateTokens:
    # Calibrated at ~2.5 bytes/token (``bytes * 2 // 5``) to stay above the
    # ~2.83 bytes/token measured on real content \u2014 see estimate_tokens (#17).
    def test_short_text(self):
        assert estimate_tokens("hello") == 5 * 2 // 5  # 5 bytes -> 2 tokens
        assert estimate_tokens("hello world") == 11 * 2 // 5  # 11 bytes -> 4

    def test_empty_text(self):
        assert estimate_tokens("") == 0

    def test_unicode_text(self):
        text = "hello w\u00f6rld"  # 12 bytes in UTF-8
        assert estimate_tokens(text) == 12 * 2 // 5


class TestShouldExclude:
    def test_always_excluded_git(self):
        assert _should_exclude(".git/config", (".git",)) is True

    def test_always_excluded_pycache(self):
        assert _should_exclude("__pycache__/module.pyc", ("__pycache__",)) is True

    def test_user_pattern(self):
        assert _should_exclude("node_modules/pkg/index.js", ("node_modules",)) is True

    def test_glob_pattern(self):
        assert _should_exclude("build/output.js", ("build/*",)) is True

    def test_no_match(self):
        assert _should_exclude("src/main.py", ("__pycache__",)) is False

    def test_graphlm_own_outputs_excluded(self):
        """graphlm's own GRAPH.* / GRAPH_DIFF.* artifacts are never re-ingested."""
        from graphlm.scanner import _ALWAYS_EXCLUDE

        pats = tuple(_ALWAYS_EXCLUDE)
        for name in ("GRAPH.md", "GRAPH.json", "GRAPH.html", "GRAPH_DIFF.md", "GRAPH_DIFF.json"):
            assert _should_exclude(name, pats) is True, name

    def test_user_graph_named_files_not_excluded(self):
        """The exclusion is named, not a broad GRAPH* glob, so user files survive."""
        from graphlm.scanner import _ALWAYS_EXCLUDE

        pats = tuple(_ALWAYS_EXCLUDE)
        for name in ("GRAPHICS.md", "GRAPHITE.json", "my_GRAPH.md", "docs/GRAPHING.md"):
            assert _should_exclude(name, pats) is False, name


class TestIsBinary:
    def test_binary_extensions(self):
        for ext in [".png", ".jpg", ".mp4", ".zip", ".so", ".pyc"]:
            assert _is_binary(Path(f"file{ext}")) is True

    def test_text_extensions(self):
        for ext in [".py", ".js", ".html", ".css", ".toml", ".sql", ".md"]:
            assert _is_binary(Path(f"file{ext}")) is False


class TestScanResult:
    def test_result_has_all_fields(self, small_project):
        result = scan_project(small_project)
        assert isinstance(result.tree, str)
        assert isinstance(result.file_fragments, list)
        assert isinstance(result.skipped_count, int)
        assert isinstance(result.excluded_patterns, tuple)

    def test_tree_contains_project_name(self, small_project):
        result = scan_project(small_project)
        assert small_project.name in result.tree


class TestScanProject:
    def test_small_project_scans_all_files(self, small_project):
        result = scan_project(small_project)
        # Should find main.py, mylib/__init__.py, mylib/helpers.py
        paths = [f.rel_path for f in result.file_fragments]
        assert "main.py" in paths
        assert "mylib/__init__.py" in paths
        assert "mylib/helpers.py" in paths

    def test_small_project_excludes_tests_by_default_includes(self, small_project):
        result = scan_project(small_project, include_tests=True)
        paths = [f.rel_path for f in result.file_fragments]
        assert "test_helpers.py" in paths

    def test_small_project_excludes_test_files_when_disabled(self, small_project):
        result = scan_project(small_project, include_tests=False)
        paths = [f.rel_path for f in result.file_fragments]
        assert "test_helpers.py" not in paths

    def test_medium_project_scans_correct_files(self, medium_project):
        result = scan_project(medium_project, include_tests=True)
        paths = [f.rel_path for f in result.file_fragments]
        assert "pyproject.toml" in paths
        assert "src/__init__.py" in paths
        assert "src/core/__init__.py" in paths
        assert "src/utils/__init__.py" in paths
        # Should include SQL migration
        migration_paths = [p for p in paths if p.endswith(".sql")]
        assert len(migration_paths) >= 1
        # Should include tests when enabled
        test_paths = [p for p in paths if "test" in p]
        assert len(test_paths) >= 2

    def test_max_files_enforced(self, medium_project):
        result = scan_project(medium_project, max_files=2)
        assert len(result.file_fragments) <= 2

    def test_max_file_chars_truncates(self, medium_project):
        result = scan_project(medium_project, max_file_chars=10)
        for frag in result.file_fragments:
            assert len(frag.content) <= 10

    def test_file_fragment_has_estimated_tokens(self, small_project):
        result = scan_project(small_project)
        for frag in result.file_fragments:
            assert isinstance(frag, FileFragment)
            assert isinstance(frag.estimated_tokens, int)
            assert frag.estimated_tokens > 0

    def test_excluded_patterns_reduce_count(self, large_project):
        result = scan_project(large_project, exclude_patterns=("*js*",))
        paths = [f.rel_path for f in result.file_fragments]
        for p in paths:
            assert "js" not in p.lower() or not p.endswith(".js")

    def test_source_outranks_docs_under_file_cap(self, tmp_path):
        # Regression for #19: under a tight max_files cap, source (.py) must be
        # scanned in preference to documentation (.md), so a doc-heavy repo
        # doesn't starve the AST import graph. Many docs + a few modules, cap
        # smaller than the doc count.
        project = tmp_path / "proj"
        project.mkdir()
        for i in range(30):
            (project / f"doc{i:02d}.md").write_text(f"# doc {i}\n")
        for i in range(5):
            (project / f"mod{i}.py").write_text("x = 1\n")

        result = scan_project(project, max_files=6)
        scanned = {f.rel_path for f in result.file_fragments}
        py = {p for p in scanned if p.endswith(".py")}
        # All 5 source modules must be scanned despite 30 docs competing.
        assert py == {f"mod{i}.py" for i in range(5)}

    def test_nonexistent_directory_raises(self):
        with pytest.raises(FileNotFoundError):
            scan_project(Path("/nonexistent/path/xyz"))

    def test_external_symlinked_file_absent_from_tree(self, tmp_path):
        # A symlinked FILE pointing outside the project must not appear in the
        # directory tree (previously only symlinked dirs were guarded).
        outside = tmp_path / "outside"
        outside.mkdir()
        secret = outside / "leak.py"
        secret.write_text("SECRET = 'do-not-scan'\n")

        project = tmp_path / "project"
        project.mkdir()
        (project / "main.py").write_text("print('hi')\n")
        link = project / "linked.py"
        try:
            link.symlink_to(secret)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not supported on this platform")

        result = scan_project(project)
        assert "linked.py" not in result.tree
        paths = [f.rel_path for f in result.file_fragments]
        assert "linked.py" not in paths
        assert "main.py" in paths

    def test_external_symlink_does_not_consume_max_files_slot(self, tmp_path):
        # An escaping symlink must be dropped BEFORE the max_files slice, or it
        # evicts a real file. Name it so it sorts first (aaa_) to prove the slot
        # isn't consumed even in the worst-case ordering.
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "leak.py").write_text("SECRET = 1\n")

        project = tmp_path / "project"
        project.mkdir()
        (project / "zzz_a.py").write_text("a = 1\n")
        (project / "zzz_b.py").write_text("b = 1\n")
        try:
            (project / "aaa_linked.py").symlink_to(outside / "leak.py")
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not supported on this platform")

        # With only 2 slots and the symlink sorting first, both real files must
        # still be scanned — the symlink must not take a slot.
        result = scan_project(project, max_files=2)
        paths = {f.rel_path for f in result.file_fragments}
        assert "zzz_a.py" in paths
        assert "zzz_b.py" in paths
        assert "aaa_linked.py" not in paths


class TestTreeBounds:
    """The pass-1 tree must be size-bounded regardless of repo size (#17)."""

    def test_per_directory_cap_emits_marker_and_omits_extras(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        # One directory with far more than the cap of listable children.
        big = project / "many"
        big.mkdir()
        for i in range(300):
            (big / f"f{i:03d}.py").write_text("x = 1\n")
        (project / "keep.py").write_text("y = 1\n")

        result = scan_project(project, max_tree_entries_per_dir=200)
        lines = result.tree.split("\n")
        # Exactly 200 of the 300 files are listed, plus one marker.
        listed = [ln for ln in lines if ln.strip().startswith("many/f")]
        assert len(listed) == 200
        marker = [ln for ln in lines if "more entries not shown" in ln]
        assert len(marker) == 1
        # The omitted count is exact (300 listable - 200 shown = 100).
        assert "100 more entries not shown" in marker[0]

    def test_shown_subdirectories_still_recurse(self, tmp_path):
        # A directory under the cap must still have its children walked — the
        # two-phase refactor must not stop recursion for shown dirs.
        project = tmp_path / "proj"
        project.mkdir()
        sub = project / "pkg"
        sub.mkdir()
        (sub / "deep.py").write_text("z = 1\n")
        (project / "top.py").write_text("a = 1\n")

        result = scan_project(project, max_tree_entries_per_dir=200)
        assert "pkg/deep.py" in result.tree

    def test_build_and_cache_dirs_excluded_from_tree(self, tmp_path):
        # Regression for #17: Rust target/, hypothesis caches, etc. must never
        # reach the tree — they were the bulk of the 400KB argus pass-1 prompt.
        project = tmp_path / "proj"
        project.mkdir()
        (project / "main.py").write_text("print('hi')\n")
        for junk in ("target", ".hypothesis", "dist", "build", ".ruff_cache", "node_modules"):
            d = project / junk
            d.mkdir()
            (d / "artifact.py").write_text("x = 1\n")
        # A nested Rust-crate target/ (the real argus shape).
        nested = project / "crates" / "foo" / "target"
        nested.mkdir(parents=True)
        (nested / "junk.py").write_text("y = 1\n")

        result = scan_project(project)
        for junk in ("target/", ".hypothesis/", "dist/", "build/", ".ruff_cache/", "node_modules/"):
            assert junk not in result.tree, f"{junk} leaked into tree"
        # Real source survives.
        assert "main.py" in result.tree
        assert "crates/" in result.tree
        paths = {f.rel_path for f in result.file_fragments}
        assert "main.py" in paths
        assert not any("target" in p for p in paths)

    def test_total_line_ceiling_stops_walk(self, tmp_path):
        # Many directories, each UNDER the per-dir cap, must still be bounded by
        # the absolute total-lines ceiling — the per-dir cap alone only bounds
        # the tree at per_dir × num_dirs, so the total backstop is what holds on
        # a repo with many directories. 200 dirs (== the default per-dir cap, so
        # the root lists them all) × 30 files (< the cap) ≈ 6000 lines, over the
        # default 200 × 25 = 5000 ceiling, and no per-dir cap fires.
        from graphlm.scanner import _MAX_TREE_ENTRIES_PER_DIR, _TREE_TOTAL_LINE_MULTIPLIER

        ceiling = _MAX_TREE_ENTRIES_PER_DIR * _TREE_TOTAL_LINE_MULTIPLIER
        project = tmp_path / "proj"
        project.mkdir()
        for d in range(_MAX_TREE_ENTRIES_PER_DIR):
            sub = project / f"d{d:03d}"
            sub.mkdir()
            for i in range(30):
                (sub / f"f{i:02d}.py").write_text("x = 1\n")

        result = scan_project(project)
        lines = result.tree.split("\n")
        assert any(f"tree truncated at {ceiling} total lines" in ln for ln in lines)
        # Bounded: the ceiling of tree_lines plus the single final marker.
        assert len(lines) <= ceiling + 1
        # No per-directory marker fired (every dir is under the cap).
        assert not any("more entries not shown" in ln for ln in lines)


class TestIsSensitiveFile:
    def test_pem_files_are_sensitive(self):
        assert _is_sensitive_file(Path("cert.pem")) is True

    def test_key_files_are_sensitive(self):
        assert _is_sensitive_file(Path("server.key")) is True

    def test_crt_files_are_sensitive(self):
        assert _is_sensitive_file(Path("ca.crt")) is True

    def test_env_production_is_sensitive(self):
        assert _is_sensitive_file(Path("env.production")) is True

    def test_secrets_filename_is_sensitive(self):
        assert _is_sensitive_file(Path("secrets.yml")) is True

    def test_credentials_filename_is_sensitive(self):
        assert _is_sensitive_file(Path("credentials.json")) is True

    def test_private_key_filename_is_sensitive(self):
        assert _is_sensitive_file(Path("private_key.pem")) is True

    def test_api_key_filename_is_sensitive(self):
        assert _is_sensitive_file(Path("api_key.txt")) is True

    def test_normal_py_file_is_not_sensitive(self):
        assert _is_sensitive_file(Path("main.py")) is False

    def test_env_example_is_not_sensitive(self):
        assert _is_sensitive_file(Path(".env.example")) is False

    def test_arbitrary_env_variant_is_sensitive(self):
        # The old fixed allowlist missed unlisted variants like .env.qa / .env.test.
        for name in (".env", ".env.qa", ".env.test", ".env.production", ".env.foo"):
            assert _is_sensitive_file(Path(name)) is True, name

    def test_env_template_variants_are_not_sensitive(self):
        # Non-secret templates must stay scannable.
        for name in (".env.example", ".env.sample", ".env.template", ".env.dist"):
            assert _is_sensitive_file(Path(name)) is False, name

    def test_gitignore_is_not_sensitive(self):
        assert _is_sensitive_file(Path(".gitignore")) is False


class TestRedactSecrets:
    def test_redacts_aws_access_key(self):
        content = "AWS_ACCESS_KEY = 'AKIAIOSFODNN7EXAMPLE'"
        redacted = _redact_secrets(content)
        assert "[REDACTED:AWS_ACCESS_KEY]" in redacted
        assert "AKIAIOSFODNN7EXAMPLE" not in redacted

    def test_redacts_github_token(self):
        content = "GITHUB_TOKEN=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"
        redacted = _redact_secrets(content)
        assert "[REDACTED:GITHUB_TOKEN]" in redacted
        assert "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in redacted

    def test_redacts_private_key_headers(self):
        content = "-----BEGIN RSA PRIVATE KEY-----\nsome key data\n-----END RSA PRIVATE KEY-----"
        redacted = _redact_secrets(content)
        assert "[REDACTED:PRIVATE_KEY_HEADER]" in redacted
        assert "BEGIN RSA PRIVATE KEY" not in redacted
        assert "END RSA PRIVATE KEY" not in redacted

    def test_redacts_password_assignment(self):
        content = 'password = "mysecretpass123"'
        redacted = _redact_secrets(content)
        assert "[REDACTED:PASSWORD]" in redacted
        assert "mysecretpass123" not in redacted

    def test_does_not_redact_none_password(self):
        content = "password = none"
        redacted = _redact_secrets(content)
        assert "none" in redacted

    def test_redacts_connection_string(self):
        content = "postgres://user:p4ssw0rd@localhost/db"
        redacted = _redact_secrets(content)
        assert "[REDACTED:CONN_STRING_PASSWORD]" in redacted
        assert "p4ssw0rd" not in redacted

    def test_leaves_plain_code_untouched(self):
        content = "x = 42\nname = 'hello'\ndef foo(): pass"
        redacted = _redact_secrets(content)
        assert redacted == content

    def test_redacts_api_key_assignment(self):
        content = 'api_key: "sk-1234567890abcdefghijklmnop"'
        redacted = _redact_secrets(content)
        assert "[REDACTED:API_KEY]" in redacted
