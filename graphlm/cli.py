"""CLI entry point — Typer-based command-line interface."""

from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer(
    name="graphlm",
    help="Generate codebase graphs (Markdown + JSON) from any project directory.",
    add_completion=False,
)


def _resolve_version() -> str:
    """graphlm's version for ``--version``.

    ``provenance.graphlm_version()`` reads installed package metadata (which
    tracks ``pyproject.toml``) and returns ``None`` in an un-installed source
    checkout. There is no better source in that case — it already wraps the only
    metadata API — so report the checkout state rather than printing ``None``.
    """
    from graphlm.provenance import graphlm_version

    return graphlm_version() or "unknown (source checkout)"


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"graphlm {_resolve_version()}")
        raise typer.Exit()


#: Default output subdirectory inside the scanned project (when -o is absent).
GRAPHLM_OUTPUT_DIRNAME = ".graphlm"


def output_destination(project_dir: Path, output_dir: str | None) -> Path:
    """Directory for GRAPH.* files.

    ``-o`` is honored literally (the user named the directory). Otherwise the
    output lands in a ``.graphlm/`` subdirectory of the scanned project — kept
    out of the project root so it doesn't clutter the tree, and excluded from
    scanning so a re-run never ingests its own map.
    """
    if output_dir:
        return Path(output_dir)
    return Path(project_dir) / GRAPHLM_OUTPUT_DIRNAME


def _do_install_skill(
    harness: str, project_dir: Path | None, local: bool, force: bool
) -> None:
    """Run --install-skill: install the agent guide and report the outcome."""
    from graphlm.skills import SUPPORTED_HARNESSES, install_skill

    harness = harness.lower()
    if harness not in SUPPORTED_HARNESSES:
        typer.echo(
            f"Error: unknown harness {harness!r}. Supported: "
            f"{', '.join(SUPPORTED_HARNESSES)}.",
            err=True,
        )
        raise typer.Exit(2)
    if local and project_dir is None:
        typer.echo(
            "Error: --skill-local needs a PROJECT_DIR. e.g. "
            f"'graphlm . --install-skill {harness} --skill-local'.",
            err=True,
        )
        raise typer.Exit(2)

    try:
        result = install_skill(
            harness, project_dir=project_dir, local=local, force=force
        )
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(2)
    if result.skipped:
        typer.echo(
            f"Skipped: {result.path} already exists (use --skill-force to "
            f"overwrite)."
        )
    else:
        typer.echo(f"Installed {harness} graphlm guide → {result.path}")
    if result.note:
        typer.echo("")
        typer.echo(result.note)


def _do_serve(project_dir: Path | None, output_dir: str | None) -> None:
    """Run --serve: expose the generated map to a coding agent over MCP (stdio).

    The map must already exist — serving never triggers a paid LLM run (the
    agent is the scheduler, ADR-001). The existence check runs *before* the
    ``mcp`` import so a missing map reports the actionable problem (run
    ``graphlm .``) rather than a missing extra.
    """
    from graphlm.query import MapUnavailable, load_map

    project = project_dir if project_dir is not None else Path(".")
    json_path = output_destination(project, output_dir) / "GRAPH.json"
    try:
        load_map(json_path)
    except MapUnavailable as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(2)
    try:
        from graphlm.mcp_server import run_server
    except ImportError:
        typer.echo(
            "Error: --serve needs the 'mcp' extra. Install with "
            "`uv tool install 'graphlm[mcp]'` (or `pip install 'graphlm[mcp]'`).",
            err=True,
        )
        raise typer.Exit(2)
    run_server(project.resolve(), json_path.resolve())


@app.command()
def main(
    project_dir: Path | None = typer.Argument(
        None,
        help="Path to the project directory to analyze.",
    ),
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show the graphlm version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
    install_skill: str | None = typer.Option(
        None,
        "--install-skill",
        help="Install an agent guide teaching a coding harness to use graphlm's "
        "map, then exit. HARNESS is 'claude' or 'codex'. Installs user-global by "
        "default; combine with --skill-local to write into the project.",
        metavar="HARNESS",
    ),
    skill_local: bool = typer.Option(
        False,
        "--skill-local",
        help="With --install-skill: write into the scanned project instead of "
        "the user-global config dir.",
    ),
    skill_force: bool = typer.Option(
        False,
        "--skill-force",
        help="With --install-skill: overwrite an existing guide instead of "
        "skipping it.",
    ),
    serve: bool = typer.Option(
        False,
        "--serve",
        help="Serve the generated map to a coding agent over MCP (stdio) and "
        "exit when the client disconnects. Needs the 'mcp' extra "
        "(graphlm[mcp]) and an existing map (run graphlm first). PROJECT_DIR "
        "defaults to '.'; -o points at the map's directory as usual. Register "
        "with e.g. `claude mcp add graphlm -- graphlm --serve /path/to/repo`.",
    ),
    output_dir: str = typer.Option(
        None,
        "-o",
        "--output-dir",
        help="Output directory for GRAPH.md/json/html (default: the scanned project).",
    ),
    base_url: str = typer.Option(
        None,
        "-b",
        "--base-url",
        help="LLM API base URL (or set GRAPHLM_BASE_URL env var).",
    ),
    api_key: str = typer.Option(
        None,
        "-k",
        "--api-key",
        help="LLM API key (or set GRAPHLM_API_KEY env var).",
    ),
    model: str = typer.Option(
        None,
        "-m",
        "--model",
        help="Model name (or set GRAPHLM_MODEL env var).",
    ),
    max_files: int = typer.Option(
        200,
        "--max-files",
        help="Maximum number of files to scan initially.",
    ),
    max_file_chars: int = typer.Option(
        4000,
        "--max-file-chars",
        help="Maximum characters per file.",
    ),
    max_pass2_files: int = typer.Option(
        80,
        "--max-pass2-files",
        help="Maximum files to include in pass 2 context (after LLM selects).",
    ),
    max_context: int | None = typer.Option(
        None,
        "--max-context",
        help="Maximum context window in tokens "
        "(default: GRAPHLM_MAX_CONTEXT env var, else 120000).",
    ),
    timeout: float | None = typer.Option(
        None,
        "--timeout",
        help="LLM request timeout in seconds "
        "(default: GRAPHLM_TIMEOUT env var, else 300). Pass 2 is streamed, so "
        "a large project's generation can take minutes.",
    ),
    max_output_tokens: int | None = typer.Option(
        None,
        "--max-output-tokens",
        help="Max tokens the model may emit for the graph "
        "(default: GRAPHLM_MAX_OUTPUT_TOKENS env var, else 128000). A ceiling, "
        "not a reservation — it is NOT taken out of the input budget "
        "(--max-context), since input and output ceilings are independent on "
        "the target endpoint (#25/#26). Lower it only on an endpoint that "
        "bounds prompt+generation together (e.g. vLLM max_model_len).",
    ),
    no_tests: bool = typer.Option(
        False,
        "--no-tests",
        help="Exclude test files from analysis.",
    ),
    exclude: list[str] = typer.Option(
        [],
        "--exclude",
        help="Exclude pattern (repeatable). e.g. __pycache__ .git",
    ),
    no_redact: bool = typer.Option(
        False,
        "--no-redact",
        help="Do not redact secret-like patterns from file content.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Analyze and show context stats without calling the LLM.",
    ),
    no_ast: bool = typer.Option(
        False,
        "--no-ast",
        help="Skip Tree-sitter AST parsing for deterministic import edges.",
    ),
    no_html: bool = typer.Option(
        False,
        "--no-html",
        help="Do not generate GRAPH.html visualization output.",
    ),
    no_diff: bool = typer.Option(
        False,
        "--no-diff",
        help="Do not write the GRAPH_DIFF.* graph-vs-graph diff (what changed "
        "in the map since the prior run).",
    ),
    no_show_cycles: bool = typer.Option(
        False,
        "--no-show-cycles",
        help="Do not show import cycle detection results.",
    ),
    cycle_threshold: float = typer.Option(
        0.0,
        "--cycle-threshold",
        help="Only show cycles with risk score >= this value.",
    ),
) -> None:
    """Analyze a project directory and produce a codebase graph (Markdown + JSON).

    Two-pass strategy:
    1. LLM identifies key files from directory tree only
    2. LLM produces the graph from tree + selected files
    """
    from graphlm import generate_graph, GraphLLError

    # --install-skill short-circuits the analysis pipeline: drop the agent guide
    # and exit. It does not need (or use) an LLM, so it runs before any config.
    if install_skill is not None:
        _do_install_skill(install_skill, project_dir, skill_local, skill_force)
        raise typer.Exit(0)

    # --serve likewise short-circuits: no LLM, no scan — just the map over MCP.
    if serve:
        _do_serve(project_dir, output_dir)
        raise typer.Exit(0)

    # project_dir is optional in the signature so --install-skill / --serve can
    # run without it; for the analysis path it's required.
    if project_dir is None:
        typer.echo(
            "Error: missing PROJECT_DIR. Pass a directory to analyze, or use "
            "--install-skill <harness> / --serve. See 'graphlm --help'.",
            err=True,
        )
        raise typer.Exit(2)

    typer.echo(f"Scanning {project_dir}...", err=True)

    try:
        result = generate_graph(
            project_dir=project_dir,
            base_url=base_url,
            api_key=api_key,
            model=model,
            output_dir=None,
            max_file_chars=max_file_chars,
            max_files=max_files,
            max_pass2_files=max_pass2_files,
            max_context=max_context,
            timeout=timeout,
            max_output_tokens=max_output_tokens,
            include_tests=not no_tests,
            exclude_patterns=tuple(exclude),
            dry_run=dry_run,
            redact_secrets=not no_redact,
            ast=not no_ast,
            show_cycles=not no_show_cycles,
            cycle_threshold=cycle_threshold,
            include_html=not no_html,
            include_diff=not no_diff,
        )
    except ValueError as e:
        typer.echo(f"Configuration error: {e}", err=True)
        raise typer.Exit(1)
    except FileNotFoundError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    except GraphLLError as e:
        typer.echo(f"LLM error: {e}", err=True)
        raise typer.Exit(1)

    if dry_run:
        typer.echo("Dry run complete. No LLM call was made.", err=True)
        typer.echo(
            f"Files selected for pass-2 analysis: {result.files_analyzed}",
            err=True,
        )
        typer.echo(
            f"Pass 1 context: ~{result.pass1_context_tokens} tokens", err=True
        )
        typer.echo(
            f"Pass 2 context: ~{result.pass2_context_tokens} tokens", err=True
        )
        typer.echo(
            f"Graph sections: tree, {len(result.graph.import_edges)} import edges, "
            f"{len(result.graph.modules)} modules, "
            f"{len(result.graph.data_flow)} data flows, "
            f"{len(result.graph.file_summaries)} file summaries, "
            f"{len(result.graph.entry_points)} entry points, "
            f"{len(result.graph.architecture_notes)} architecture notes, "
            f"{len(result.graph.quick_reference)} quick references",
            err=True,
        )
        raise typer.Exit(0)

    dest = output_destination(project_dir, output_dir)
    written = result.write(dest, include_html=not no_html, include_diff=not no_diff)
    md_path, json_path, html_path = written
    typer.echo(f"Markdown:  {md_path}", err=True)
    typer.echo(f"JSON:      {json_path}", err=True)
    if html_path:
        typer.echo(f"HTML:      {html_path}", err=True)
    if written.diff_md:
        typer.echo(f"Diff (md): {written.diff_md}", err=True)
    if written.diff_json:
        typer.echo(f"Diff (json): {written.diff_json}", err=True)

    typer.echo(
        f"Modules: {len(result.graph.modules)} | "
        f"Import edges: {len(result.graph.import_edges)} | "
        f"Data flows: {len(result.graph.data_flow)} | "
        f"Tests: {len(result.graph.test_organization)} | "
        f"Files: {len(result.graph.file_summaries)} | "
        f"Entry points: {len(result.graph.entry_points)} | "
        f"Notes: {len(result.graph.architecture_notes)} | "
        f"Lookups: {len(result.graph.quick_reference)}",
        err=True,
    )
    typer.echo("Done.", err=True)


if __name__ == "__main__":
    app()
