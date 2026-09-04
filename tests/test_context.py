"""Tests for context packing and prompt assembly."""

from graphlm.context import (
    MESSAGE_OVERHEAD_TOKENS,
    assemble_pass1_prompt,
    assemble_pass2_prompt,
    estimate_tokens,
    filter_requested_files,
)
from graphlm.models import ImportEdge
from graphlm.scanner import FileFragment, scan_project


class TestEstimateTokens:
    def test_consistent_with_scanner(self):
        # context.estimate_tokens is now the single scanner implementation,
        # re-exported — so they are the same object, not just equal (#17).
        from graphlm.scanner import estimate_tokens as scanner_estimate

        assert estimate_tokens is scanner_estimate
        text = "hello world"
        assert estimate_tokens(text) == len(text.encode("utf-8")) * 2 // 5

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

    def test_partial_edge_table_uses_non_exhaustive_framing(self):
        edges = [
            ImportEdge(from_path="src/a.ts", to_path="src/b.ts", kind="import"),
        ]
        prompt, _tokens, _truncated = assemble_pass2_prompt(
            "root/", [], deterministic_edges=edges, edges_partial=True
        )
        assert "NOT exhaustive" in prompt
        assert "relative specifiers" in prompt
        assert "truncated to fit the context budget" not in prompt
        # Complete-table wording must not be used for a known-partial list.
        assert "do not contradict or omit these parser edges" not in prompt

    def test_size_capped_and_partial_mentions_both_reasons(self):
        from graphlm.context import MESSAGE_OVERHEAD_TOKENS

        edges = [
            ImportEdge(
                from_path=f"src/mod{i}.ts", to_path=f"src/mod{j}.ts", kind="import"
            )
            for i in range(300)
            for j in range(20)
        ]
        max_context = MESSAGE_OVERHEAD_TOKENS + 2000
        prompt, _tokens, _truncated = assemble_pass2_prompt(
            "proj/",
            [],
            max_context=max_context,
            deterministic_edges=edges,
            edges_partial=True,
        )
        assert "truncated to fit the context budget" in prompt
        assert "relative specifiers" in prompt
        assert "NOT exhaustive" in prompt

    def test_instruction_block_lists_require_kind(self):
        prompt, _tokens, _truncated = assemble_pass2_prompt("root/", [])
        assert '"require"' in prompt
        assert '"static"' in prompt

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
        from graphlm.context import MESSAGE_OVERHEAD_TOKENS

        scan = scan_project(large_project)
        # Budget = the fixed output/instruction floor + a small file allowance,
        # sized so the high-priority files (config, __init__, main) fit but the
        # lower-priority ones (routes, services, migrations) get truncated. The
        # allowance is added to the reserve so this test self-tracks changes to
        # the output reserve or estimate_tokens calibration (#17/#18) instead of
        # hard-coding a magic number that churns each time the reserve moves.
        reserve = MESSAGE_OVERHEAD_TOKENS
        prompt, tokens, truncated = assemble_pass2_prompt(
            scan.tree, scan.file_fragments, max_context=reserve + 2500
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

    def test_assembled_prompt_respects_budget_with_huge_edge_table(self):
        """A very large AST-edge table must not push the assembled prompt past
        max_context. Contract: estimate_tokens(prompt) + output_reserve
        (reserved for the response and never emitted) <= max_context.
        Regression for #12 — before the edge cap, 6000 rows produced a ~62k
        prompt regardless of the budget.
        """
        from graphlm.context import MESSAGE_OVERHEAD_TOKENS

        output_reserve = MESSAGE_OVERHEAD_TOKENS
        frags = [
            FileFragment(f"src/mod{i}.py", "x" * 3000, estimate_tokens("x" * 3000))
            for i in range(40)
        ]
        # 6000 rows — far more than any realistic budget can hold verbatim.
        edges = [
            ImportEdge(
                from_path=f"src/mod{i}.py", to_path=f"src/mod{j}.py", kind="import"
            )
            for i in range(300)
            for j in range(20)
        ]
        tree = "proj/\n" + "\n".join(f"  src/mod{i}.py" for i in range(40))

        # Budgets above the output/instruction floor (floor-relative so the test
        # tracks reserve changes rather than hard-coding numbers — #17/#18).
        for extra in (2000, 26000, 86000):
            max_context = output_reserve + extra
            prompt, reported, truncated = assemble_pass2_prompt(
                tree, frags, max_context=max_context, deterministic_edges=edges
            )
            assert estimate_tokens(prompt) + output_reserve <= max_context, (
                f"prompt overflowed at max_context={max_context}"
            )

    def test_huge_edge_table_is_truncated_with_non_exhaustive_framing(self):
        """When the edge table is capped, the framing must tell the model the
        list is NOT exhaustive (so it still infers the dropped edges), and only
        a subset of rows is emitted.
        """
        from graphlm.context import MESSAGE_OVERHEAD_TOKENS

        edges = [
            ImportEdge(
                from_path=f"src/mod{i}.py", to_path=f"src/mod{j}.py", kind="import"
            )
            for i in range(300)
            for j in range(20)
        ]
        # Enough room above the reserve floor for a capped-but-present edge table.
        max_context = MESSAGE_OVERHEAD_TOKENS + 2000
        prompt, _tokens, _truncated = assemble_pass2_prompt(
            "proj/", [], max_context=max_context, deterministic_edges=edges
        )
        assert "NOT exhaustive" in prompt
        assert "showing" in prompt.lower()
        # Not all 6000 rows are present.
        assert prompt.count("| src/mod") < len(edges)

    def test_prompt_budget_exact_across_rounding_boundaries(self):
        """estimate_tokens floors each section, so per-section sums can
        under-count the joined prompt. The final whole-prompt guard must keep
        estimate_tokens(prompt) + output_reserve <= max_context at every budget,
        including ones where the section-sum estimate would have overshot.
        """
        from graphlm.context import MESSAGE_OVERHEAD_TOKENS

        output_reserve = MESSAGE_OVERHEAD_TOKENS
        frags = [
            FileFragment(f"src/mod{i}.py", "x" * 3000, estimate_tokens("x" * 3000))
            for i in range(40)
        ]
        edges = [
            ImportEdge(
                from_path=f"src/very/deep/path/mod{i}.py",
                to_path=f"src/other/mod{j}.py",
                kind="import",
            )
            for i in range(300)
            for j in range(20)
        ]
        tree = "proj/\n" + "\n".join(f"  m{i}" for i in range(40))
        # Dense sweep across the rounding-sensitive region, starting just above
        # the output/instruction floor (below it the floor wins and no budget
        # guarantee is claimed — see assemble_pass2_prompt docstring). Sweep
        # bounds are floor-relative so this tracks reserve changes (#17/#18).
        # +2000 clears the instruction block (~1.1k assembled) above the reserve
        # so every swept budget is above the true floor.
        start = output_reserve + 2000
        for max_context in range(start, start + 33000, 311):
            prompt, reported, _truncated = assemble_pass2_prompt(
                tree, frags, max_context=max_context, deterministic_edges=edges
            )
            assert estimate_tokens(prompt) + output_reserve <= max_context, (
                f"overflow at max_context={max_context}"
            )
            # Reported total is the authoritative measured value.
            assert reported == estimate_tokens(prompt) + output_reserve

    def test_input_admission_reserves_only_message_overhead(self):
        """Input admission depends only on max_context and the small message
        overhead — NOT on the output budget, which is a separate ceiling (#25).
        The reported total is the measured prompt plus exactly the overhead
        reserve, not the (potentially huge) max_tokens.
        """
        frags = [
            FileFragment(f"src/mod{i}.py", "x" * 3000, estimate_tokens("x" * 3000))
            for i in range(40)
        ]
        tree = "proj/"
        prompt, reported, _trunc = assemble_pass2_prompt(
            tree, frags, max_context=80000
        )
        # The reported total is the measured prompt + the overhead reserve only.
        assert reported == estimate_tokens(prompt) + MESSAGE_OVERHEAD_TOKENS
        # Sanity: a large budget admits every file (nothing reserved for output).
        assert _trunc == []

    def test_small_edge_table_keeps_exhaustive_framing(self):
        """A small edge table that fits must keep the strong 'do not omit'
        framing and emit every row (no false truncation).
        """
        edges = [
            ImportEdge(from_path="a.py", to_path="b.py", kind="import"),
            ImportEdge(from_path="b.py", to_path="c.py", kind="import"),
        ]
        prompt, _tokens, _truncated = assemble_pass2_prompt(
            "proj/", [], max_context=120000, deterministic_edges=edges
        )
        assert "do not" in prompt and "contradict or omit" in prompt
        assert "NOT exhaustive" not in prompt
        assert "a.py" in prompt and "b.py" in prompt and "c.py" in prompt

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
