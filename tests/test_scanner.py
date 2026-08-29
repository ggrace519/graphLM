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
    def test_short_text(self):
        assert estimate_tokens("hello") == 5 // 4  # 5 bytes, 1 token
        assert estimate_tokens("hello world") == 11 // 4  # 11 bytes, 2 tokens

    def test_empty_text(self):
        assert estimate_tokens("") == 0

    def test_unicode_text(self):
        text = "hello w\u00f6rld"  # 12 bytes in UTF-8
        assert estimate_tokens(text) == 12 // 4


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

    def test_nonexistent_directory_raises(self):
        with pytest.raises(FileNotFoundError):
            scan_project(Path("/nonexistent/path/xyz"))


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
