"""Tests for context packing and prompt assembly."""

from graphlm.context import (
    PASS1_ESTIMATED_TREE_TOKENS,
    assemble_pass1_prompt,
    assemble_pass2_prompt,
    estimate_tokens,
    filter_requested_files,
)
from graphlm.models import ImportEdge
from graphlm.scanner import FileFragment, scan_project


class TestEstimateTokens:
    def test_consistent_with_scanner(self):
        text = "hello world"
        assert estimate_tokens(text) == len(text.encode("utf-8")) // 4

    def test_empty(self):
        assert estimate_tokens("") == 0


class TestPass1Prompt:
    def test_prompt_contains_tree(self, small_project):
        from graphlm.scanner import scan_project

        scan = scan_project(small_project)
        prompt = assemble_pass1_prompt(scan.tree)
        assert small_project.name in prompt
        assert "requested_files" in prompt

    def test_prompt_contains_instructions(self):
        prompt = assemble_pass1_prompt("root/\n")
        assert "JSON object" in prompt
        assert "Rules:" in prompt


class TestPass2Prompt:
    def test_prompt_contains_tree_and_files(self, small_project):
        from graphlm.scanner import scan_project

        scan = scan_project(small_project)
        prompt, tokens, _truncated = assemble_pass2_prompt(scan.tree, scan.file_fragments)
        assert scan.tree in prompt
        for frag in scan.file_fragments:
            assert f"File: {frag.rel_path}" in prompt
            assert frag.content[:50] in prompt

    def test_prompt_contains_instructions(self):
        prompt, _tokens, _truncated = assemble_pass2_prompt("root/", [])
        assert "JSON object" in prompt
        assert "import_edges" in prompt
        assert "modules" in prompt
        assert "data_flow" in prompt
        assert "architecture_notes" in prompt
        assert "quick_reference" in prompt

    def test_prompt_includes_deterministic_edges(self):
        edges = [
            ImportEdge(
                from_path="app/main.py", to_path="app/routes.py", kind="from"
            ),
            ImportEdge(
                from_path="app/routes.py",
                to_path="app/services.py",
                kind="from",
            ),
        ]
        prompt, _tokens, _truncated = assemble_pass2_prompt(
            "root/", [], deterministic_edges=edges
        )
        assert "## Deterministic import edges (AST ground truth)" in prompt
        assert "app/main.py" in prompt
        assert "app/routes.py" in prompt
        assert "app/services.py" in prompt
        assert "ground truth" in prompt.lower()

    def test_prompt_omits_deterministic_edges_when_absent(self):
        prompt, _tokens, _truncated = assemble_pass2_prompt("root/", [])
        assert "Deterministic import edges" not in prompt
        prompt_empty, _, _ = assemble_pass2_prompt(
            "root/", [], deterministic_edges=[]
        )
        assert "Deterministic import edges" not in prompt_empty

    def test_prompt_database_schema_application_only(self):
        prompt, _tokens, _truncated = assemble_pass2_prompt("root/", [])
        lower = prompt.lower()
        assert "application under analysis" in lower
        assert "test fixtures" in lower
        assert "null" in lower

    def test_token_estimate_increases_with_files(self, small_project):
        from graphlm.scanner import scan_project

        scan = scan_project(small_project)
        _, tokens0, _ = assemble_pass2_prompt(scan.tree, [])
        _, tokens1, _ = assemble_pass2_prompt(scan.tree, scan.file_fragments[:1])
        _, tokens_all, _ = assemble_pass2_prompt(scan.tree, scan.file_fragments)
        assert tokens1 > tokens0
        assert tokens_all > tokens1


class TestFilterRequestedFiles:
    def test_filters_to_requested_only(self, medium_project):
        from graphlm.scanner import scan_project

        scan = scan_project(medium_project)
        requested = ["pyproject.toml", "main.py"]
        # Only pyproject.toml exists in scan
        matched = filter_requested_files(scan, requested, max_files=10)
        matched_paths = {f.rel_path for f in matched}
        assert "pyproject.toml" in matched_paths

    def test_enforces_max_files(self, large_project):
        from graphlm.scanner import scan_project

        scan = scan_project(large_project, include_tests=True)
        # Request more files than max
        requested = [f.rel_path for f in scan.file_fragments]
        matched = filter_requested_files(scan, requested, max_files=3)
        assert len(matched) <= 3

    def test_empty_requested_returns_empty(self, small_project):
        scan = scan_project(small_project)
        matched = filter_requested_files(scan, [], max_files=10)
        assert matched == []

    def test_deterministic_ordering(self, large_project):
        from graphlm.scanner import scan_project

        scan = scan_project(large_project)
        requested = [f.rel_path for f in scan.file_fragments[:10]]
        matched1 = filter_requested_files(scan, requested, max_files=10)
        matched2 = filter_requested_files(scan, requested, max_files=10)
        paths1 = [f.rel_path for f in matched1]
        paths2 = [f.rel_path for f in matched2]
        assert paths1 == paths2

    def test_fuzzy_match(self, medium_project):
        from graphlm.scanner import scan_project

        scan = scan_project(medium_project)
        # Request with slightly different path
        requested = ["src/core/__init__.py"]
        matched = filter_requested_files(scan, requested, max_files=10)
        matched_paths = {f.rel_path for f in matched}
        assert "src/core/__init__.py" in matched_paths


class TestMaxContext:
    def test_default_max_context_allows_all_files(self, small_project):
        from graphlm.scanner import scan_project

        scan = scan_project(small_project)
        prompt, tokens, truncated = assemble_pass2_prompt(
            scan.tree, scan.file_fragments
        )
        assert len(truncated) == 0
        assert len(scan.file_fragments) > 0

    def test_small_max_context_truncates_files(self, small_project):
        from graphlm.scanner import scan_project

        scan = scan_project(small_project)
        # Use a very small context that can only fit the tree
        prompt, tokens, truncated = assemble_pass2_prompt(
            scan.tree, scan.file_fragments, max_context=2000
        )
        assert len(truncated) > 0
        assert len(truncated) == len(scan.file_fragments)

    def test_medium_max_context_truncates_some_files(self, large_project):
        from graphlm.scanner import scan_project

        scan = scan_project(large_project)
        # Use a context that fits some but not all files
        prompt, tokens, truncated = assemble_pass2_prompt(
            scan.tree, scan.file_fragments, max_context=5000
        )
        assert len(truncated) > 0
        # At least the tree should be present
        assert scan.tree in prompt

    def test_truncated_are_lower_priority_files(self, large_project):
        from graphlm.scanner import scan_project

        scan = scan_project(large_project)
        prompt, tokens, truncated = assemble_pass2_prompt(
            scan.tree, scan.file_fragments, max_context=12000
        )
        # High-priority files (config, __init__, main) should fit first
        # Lower-priority files (routes, services, migrations) get truncated
        included = {f.rel_path for f in scan.file_fragments} - set(truncated)
        # pyproject.toml (rank 0 config) should be included
        assert "pyproject.toml" in included
        # app/main.py (rank 2 entry point) should be included
        assert "app/main.py" in included
        # Some routes/services/migrations should be truncated
        assert len(truncated) > 0
        # The lower-priority files are truncated, not higher priority ones
        assert "migrations/" not in " ".join(included)

    def test_truncated_files_not_in_prompt(self, large_project):
        from graphlm.scanner import scan_project

        scan = scan_project(large_project)
        prompt, tokens, truncated = assemble_pass2_prompt(
            scan.tree, scan.file_fragments, max_context=5000
        )
        for path in truncated:
            assert f"File: {path}" not in prompt

    def test_config_max_context_in_settings(self, monkeypatch):
        monkeypatch.setenv("GRAPHLM_BASE_URL", "http://test.local/v1")
        monkeypatch.setenv("GRAPHLM_API_KEY", "test-key")
        monkeypatch.setenv("GRAPHLM_MODEL", "test-model")
        monkeypatch.setenv("GRAPHLM_MAX_CONTEXT", "64000")

        from graphlm.config import Settings

        settings = Settings.from_env()
        assert settings.max_context == 64000

    def test_settings_default_max_context(self, monkeypatch):
        monkeypatch.setenv("GRAPHLM_BASE_URL", "http://test.local/v1")
        monkeypatch.setenv("GRAPHLM_API_KEY", "test-key")
        monkeypatch.setenv("GRAPHLM_MODEL", "test-model")
        monkeypatch.delenv("GRAPHLM_MAX_CONTEXT", raising=False)

        from graphlm.config import Settings

        settings = Settings.from_env()
        assert settings.max_context == 120000
