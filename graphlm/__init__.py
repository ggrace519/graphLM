"""graphLM — Generate codebase graphs from any project directory.

Usage as a library:

    from graphlm import generate_graph

    result = generate_graph("/path/to/project")
    md_path, json_path = result.write(output_dir="./output")

Usage as a CLI:

    graphlm /path/to/project -o ./output
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import logging

from graphlm.config import Settings
from graphlm.context import (
    Pass2Context,
    assemble_pass1_prompt,
    assemble_pass2_prompt,
    filter_requested_files,
)
from graphlm.cycles import detect_cycles
from graphlm.llm import (
    CodebaseGraph,
    GraphLLError,
    call_llm,
)
from graphlm.models import ArchitectureNote
from graphlm.parser import build_dependency_graph, ImportEdge
from graphlm.prompts import SYSTEM_PROMPT
from graphlm.render import write_outputs
from graphlm.scanner import ScanResult, scan_project


class GraphResult:
    """Output artifacts from a graph generation run."""

    def __init__(
        self,
        graph: CodebaseGraph,
        pass1_context_tokens: int,
        pass2_context_tokens: int,
        files_analyzed: int,
    ) -> None:
        self.graph = graph
        self.pass1_context_tokens = pass1_context_tokens
        self.pass2_context_tokens = pass2_context_tokens
        self.files_analyzed = files_analyzed

    def write(
        self, output_dir: Path, *, include_html: bool = True
    ) -> tuple[Path, Path, Path | None]:
        """Write .md, .json (and optionally .html) to output_dir. Return all paths."""
        return write_outputs(self.graph, output_dir, html=include_html)


def generate_graph(
    project_dir: str | Path,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    output_dir: str | Path | None = None,
    max_file_chars: int = 4000,
    max_files: int = 200,
    max_pass2_files: int = 80,
    max_context: int = 120000,
    include_tests: bool = True,
    exclude_patterns: tuple[str, ...] = (),
    dry_run: bool = False,
    redact_secrets: bool = True,
    ast: bool = False,
) -> GraphResult:
    """Generate a codebase graph for a project directory.

    Two-pass strategy:
    1. Send directory tree to LLM → LLM identifies key files to read
    2. Send tree + key files to LLM → LLM produces the final graph

    Args:
        project_dir: Path to the project directory to analyze.
        base_url: LLM API base URL (falls back to GRAPHLM_BASE_URL env var).
        api_key: LLM API key (falls back to GRAPHLM_API_KEY env var).
        model: Model name (falls back to GRAPHLM_MODEL env var).
        output_dir: Where to write .md and .json outputs (default: current dir).
        max_file_chars: Maximum characters to read per file.
        max_files: Maximum files to scan initially.
        max_pass2_files: Maximum files to include in pass 2 context.
        max_context: Maximum context window in tokens (default: 120000).
        include_tests: Whether to include test files in the analysis.
        exclude_patterns: Additional glob patterns to exclude.
        dry_run: If True, return the scan context without calling the LLM.
        redact_secrets: If True, redact secret-like patterns from file content.
        ast: If True, run AST-based deterministic import detection and pass
            those edges to the LLM as ground truth.

    Returns:
        GraphResult with the graph and output metadata.

    Raises:
        ValueError: If configuration is invalid.
        GraphLLError: If the LLM call fails.
    """
    project_path = Path(project_dir).resolve()

    if not project_path.exists():
        raise FileNotFoundError(f"Project directory not found: {project_dir}")
    if not project_path.is_dir():
        raise NotADirectoryError(f"Not a directory: {project_dir}")

    # Resolve configuration (not needed for dry run)
    if dry_run:
        settings = None
    elif base_url or api_key or model:
        if not base_url or not api_key or not model:
            raise ValueError(
                "If any of base_url/api_key/model are provided, "
                "all three must be provided."
            )
        settings = Settings(base_url=base_url, api_key=api_key, model=model)
    else:
        try:
            settings = Settings.from_env()
        except ValueError as e:
            raise ValueError(str(e)) from None

    # Phase 1: Scan the project
    scan = scan_project(
        project_path,
        max_file_chars=max_file_chars,
        max_files=max_files,
        include_tests=include_tests,
        exclude_patterns=exclude_patterns,
        redact_secrets=redact_secrets,
    )

    # If --ast is enabled, build deterministic import edges from AST parsing
    deterministic_edges: list[ImportEdge] | None = None
    if ast:
        try:
            deterministic_edges = build_dependency_graph(
                scan.file_fragments, project_dir=project_path, max_files=max_files,
            )
        except Exception as e:
            logging.warning("AST parsing failed, continuing without it: %s", e)

    if dry_run:
        # Don't call the LLM, just show context stats
        # Simulate pass 1 selecting all scanned files
        pass2_files = scan.file_fragments[:max_pass2_files]
        pass2_prompt, pass2_tokens, _truncated = assemble_pass2_prompt(
            scan.tree, pass2_files, max_context=max_context
        )
        graph = CodebaseGraph(
            directory_tree=scan.tree,
            architecture_notes=[
                ArchitectureNote(
                    note=f"DRY RUN: {len(scan.file_fragments)} files scanned, "
                    f"{len(pass2_files)} files selected for analysis, "
                    f"{pass2_tokens} estimated pass-2 tokens"
                ),
            ],
        )
        return GraphResult(
            graph=graph,
            pass1_context_tokens=pass1_tokens(scan.tree),
            pass2_context_tokens=pass2_tokens,
            files_analyzed=len(pass2_files),
        )

    # Phase 1: LLM identifies key files from tree only
    assert settings is not None

    pass1_prompt = assemble_pass1_prompt(scan.tree)
    pass1_result_json = call_llm(
        base_url=settings.base_url,
        api_key=settings.api_key,
        model=settings.model,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=pass1_prompt,
    )
    pass1_result_json = cast(str, pass1_result_json)

    # Parse pass 1 result
    import json as _json

    try:
        pass1_data = _json.loads(pass1_result_json)
        requested_files = pass1_data.get("requested_files", [])
    except (_json.JSONDecodeError, TypeError, KeyError) as e:
        raise GraphLLError(
            f"Pass 1 LLM response was not valid JSON: {e}\n"
            f"Response: {pass1_result_json[:200]}"
        ) from e

    # Phase 2: Filter requested files and assemble context
    pass2_files = filter_requested_files(scan, requested_files, max_pass2_files)
    pass2_prompt, pass2_tokens, _truncated = assemble_pass2_prompt(
        scan.tree, pass2_files, max_context=max_context
    )

    # Phase 2: LLM produces the final graph
    assert settings is not None
    graph_result = call_llm(
        base_url=settings.base_url,
        api_key=settings.api_key,
        model=settings.model,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=pass2_prompt,
        response_format=CodebaseGraph,
    )
    graph = cast(CodebaseGraph, graph_result)
    if show_cycles:
        graph.import_cycles = [
            c for c in detect_cycles(graph.import_edges)
            if c.risk_score >= cycle_threshold
        ]

    # Write outputs if output_dir specified
    if output_dir is not None:
        write_outputs(graph, Path(output_dir))

    return GraphResult(
        graph=graph,
        pass1_context_tokens=pass1_tokens(scan.tree),
        pass2_context_tokens=pass2_tokens,
        files_analyzed=len(pass2_files),
    )


def pass1_tokens(tree: str) -> int:
    """Estimate token count for pass 1 prompt (tree + instructions)."""
    from graphlm.context import estimate_tokens

    instruction_tokens = estimate_tokens(
        "You are analyzing a project directory to determine which files "
        "are most important to read for a comprehensive codebase analysis. "
        "Return a JSON object with requested_files list."
    )
    return instruction_tokens + estimate_tokens(tree)
