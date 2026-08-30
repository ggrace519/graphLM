"""graphLM — Generate codebase graphs from any project directory.

Usage as a library:

    from graphlm import generate_graph

    result = generate_graph("/path/to/project")
    md_path, json_path, html_path = result.write("./output")

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
from graphlm.cycles import compute_sloc_map, detect_cycles
from graphlm.llm import (
    CodebaseGraph,
    GraphLLError,
    call_llm,
)
from graphlm.models import ArchitectureNote, GraphMeta, ImportEdge
from graphlm.parser import build_dependency_graph
from graphlm.prompts import SYSTEM_PROMPT
from graphlm.provenance import git_commit_sha, graphlm_version, now_utc_iso
from graphlm.render import WriteResult, write_outputs
from graphlm.scanner import ScanResult, scan_project


def _build_meta(project_path: Path) -> GraphMeta:
    """Build the provenance stamp for a run against ``project_path``.

    Failure-tolerant throughout: a non-git project yields ``commit_sha=None``,
    a non-installed checkout yields ``graphlm_version=None``. Never raises.
    """
    return GraphMeta(
        created_at=now_utc_iso(),
        commit_sha=git_commit_sha(project_path),
        graphlm_version=graphlm_version(),
    )


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
        self,
        output_dir: str | Path,
        *,
        include_html: bool = True,
        include_diff: bool = True,
    ) -> WriteResult:
        """Write .md, .json (and optionally .html + the diff) to output_dir.

        Returns a ``WriteResult`` — the ``(md, json, html)`` path tuple, with
        ``.diff_md`` / ``.diff_json`` attributes (``None`` when
        ``include_diff=False``). The diff (``GRAPH_DIFF.*``) reads the prior
        ``GRAPH.json`` in ``output_dir`` before overwriting it; see ADR-002.
        """
        return write_outputs(
            self.graph, Path(output_dir), html=include_html, diff=include_diff
        )


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
    max_context: int | None = None,
    timeout: float | None = None,
    max_output_tokens: int | None = None,
    include_tests: bool = True,
    exclude_patterns: tuple[str, ...] = (),
    dry_run: bool = False,
    redact_secrets: bool = True,
    ast: bool = True,
    show_cycles: bool = True,
    cycle_threshold: float = 0.0,
    include_html: bool = True,
    include_diff: bool = True,
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
        output_dir: Where to write GRAPH.md/json/html. None means do not write
            (the CLI defaults to the scanned project directory).
        max_file_chars: Maximum characters to read per file.
        max_files: Maximum files to scan initially.
        max_pass2_files: Maximum files to include in pass 2 context.
        max_context: Maximum context window in tokens. If None, falls back to
            the GRAPHLM_MAX_CONTEXT env var, then to 120000. An explicit value
            (e.g. from the CLI --max-context flag) takes precedence over both.
        timeout: LLM request timeout in seconds. If None, falls back to the
            GRAPHLM_TIMEOUT env var, then to 300. An explicit value (the CLI
            --timeout flag) takes precedence. Pass 2 is streamed, so a large
            project's generation can legitimately take minutes (#18).
        max_output_tokens: Max tokens the model may emit for the graph — the
            `max_tokens` the client requests. A ceiling, not a reservation: it is
            NOT taken out of the input budget (max_context), because input and
            output ceilings are independent on the target endpoint (#25). If None,
            falls back to GRAPHLM_MAX_OUTPUT_TOKENS env, then LLM_MAX_OUTPUT_TOKENS
            (the model's practical max). Truncation past even this raises a clear
            GraphLLErrorTruncated.
        include_tests: Whether to include test files in the analysis.
        exclude_patterns: Additional glob patterns to exclude.
        dry_run: If True, return the scan context without calling the LLM.
        redact_secrets: If True, redact secret-like patterns from file content.
        ast: If True (default), run AST-based deterministic import detection,
            attach those edges to the graph, and pass them to the LLM as
            ground truth. Pass False / --no-ast to skip.
        include_html: If output_dir is set, whether to also write GRAPH.html.
        include_diff: If output_dir is set, whether to also write the
            graph-vs-graph diff (GRAPH_DIFF.md/json) against the prior
            GRAPH.json in that directory. On by default; see ADR-002. Never
            reached on a --dry-run (the dry-run branch returns before any write).

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

    # Resolve the context budget: explicit arg > GRAPHLM_MAX_CONTEXT env > 120000.
    # Passing max_context=None (the CLI default when --max-context is unset) lets
    # the env var take effect; an explicit value always wins.
    if max_context is None:
        import os

        max_context = int(os.environ.get("GRAPHLM_MAX_CONTEXT", "120000"))

    # Resolve the output-token reserve: explicit arg > GRAPHLM_MAX_OUTPUT_TOKENS
    # env > LLM_MAX_OUTPUT_TOKENS default. Needed even in dry-run so the pass-2
    # estimate reserves the same budget the real call would request. This value
    # is passed to BOTH assemble_pass2_prompt (the input reserve) and call_llm
    # (the max_tokens requested), keeping the two in lock-step (#17/#18).
    if max_output_tokens is None:
        import os

        from graphlm.llm import LLM_MAX_OUTPUT_TOKENS

        max_output_tokens = int(
            os.environ.get("GRAPHLM_MAX_OUTPUT_TOKENS", str(LLM_MAX_OUTPUT_TOKENS))
        )

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

    # Resolve the request timeout: explicit arg > (settings, which already
    # carries GRAPHLM_TIMEOUT env > default when built via from_env). When
    # settings is built from explicit base_url/api_key/model it uses the default
    # timeout; an explicit `timeout` arg (the CLI --timeout flag) overrides.
    resolved_timeout = timeout if timeout is not None else (
        settings.timeout if settings is not None else None
    )

    # Phase 1: Scan the project
    scan = scan_project(
        project_path,
        max_file_chars=max_file_chars,
        max_files=max_files,
        include_tests=include_tests,
        exclude_patterns=exclude_patterns,
        redact_secrets=redact_secrets,
    )

    # Deterministic import edges from AST parsing (on by default)
    deterministic_edges: list[ImportEdge] | None = None
    if ast:
        try:
            deterministic_edges = build_dependency_graph(
                scan.file_fragments, project_dir=project_path, max_files=max_files,
            )
        except Exception as e:
            logging.warning("AST parsing failed, continuing without it: %s", e)

    sloc_map = compute_sloc_map(scan.file_fragments)

    if dry_run:
        # Don't call the LLM, just show context stats
        # Simulate pass 1 selecting all scanned files
        pass2_files = scan.file_fragments[:max_pass2_files]
        pass2_prompt, pass2_tokens, _truncated = assemble_pass2_prompt(
            scan.tree,
            pass2_files,
            max_context=max_context,
            deterministic_edges=deterministic_edges,
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
            deterministic_edges=deterministic_edges,
        )
        if show_cycles:
            graph.import_cycles = [
                c
                for c in detect_cycles(
                    deterministic_edges or [], sloc_map=sloc_map
                )
                if c.risk_score >= cycle_threshold
            ]
        # Stamp the dry-run graph too, so its provenance is consistent with a
        # real run (a --dry-run write would otherwise carry no directive).
        graph.meta = _build_meta(project_path)
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
        timeout=resolved_timeout,
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
        scan.tree,
        pass2_files,
        max_context=max_context,
        deterministic_edges=deterministic_edges,
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
        timeout=resolved_timeout,
        max_output_tokens=max_output_tokens,
    )
    graph = cast(CodebaseGraph, graph_result)
    # Fill the tree locally rather than making the model echo it back — the echo
    # alone can exceed the output-token ceiling on a large repo (argus's tree is
    # ~20k output tokens), truncating the graph before any module is described
    # (#18). The pass-2 prompt now asks the model for an empty directory_tree.
    graph.directory_tree = scan.tree
    graph.deterministic_edges = deterministic_edges
    if show_cycles:
        cycle_edges = (
            deterministic_edges
            if deterministic_edges is not None
            else graph.import_edges
        )
        graph.import_cycles = [
            c
            for c in detect_cycles(cycle_edges, sloc_map=sloc_map)
            if c.risk_score >= cycle_threshold
        ]
    else:
        graph.import_cycles = []

    # Stamp provenance locally, overwriting anything the model may have emitted
    # for `meta` (like directory_tree, meta is filled here, never trusted from
    # the LLM). The GRAPH.md refresh directive is rendered from this.
    graph.meta = _build_meta(project_path)

    # Write outputs if output_dir specified
    if output_dir is not None:
        write_outputs(graph, Path(output_dir), html=include_html, diff=include_diff)

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
