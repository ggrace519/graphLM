"""CLI entry point — Typer-based command-line interface."""

from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer(
    name="graphlm",
    help="Generate codebase graphs (Markdown + JSON) from any project directory.",
    add_completion=False,
)


@app.command()
def main(
    project_dir: Path = typer.Argument(
        ...,
        help="Path to the project directory to analyze.",
    ),
    output_dir: str = typer.Option(
        None,
        "-o",
        "--output-dir",
        help="Output directory for generated files (default: current directory).",
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
    max_context: int = typer.Option(
        120000,
        "--max-context",
        help="Maximum context window in tokens (default: 120000).",
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
    ast: bool = typer.Option(
        False,
        "--ast",
        help="Use Tree-sitter AST parsing for deterministic import edges.",
    ),
    no_html: bool = typer.Option(
        False,
        "--no-html",
        help="Do not generate HTML visualization output.",
    ),
) -> None:
    """Analyze a project directory and produce a codebase graph (Markdown + JSON).

    Two-pass strategy:
    1. LLM identifies key files from directory tree only
    2. LLM produces the graph from tree + selected files
    """
    from graphlm import generate_graph, GraphLLError

    typer.echo(f"Scanning {project_dir}...", err=True)

    try:
        result = generate_graph(
            project_dir=project_dir,
            base_url=base_url,
            api_key=api_key,
            model=model,
            output_dir=output_dir,
            max_file_chars=max_file_chars,
            max_files=max_files,
            max_pass2_files=max_pass2_files,
            max_context=max_context,
            include_tests=not no_tests,
            exclude_patterns=tuple(exclude),
            dry_run=dry_run,
            redact_secrets=not no_redact,
            ast=ast,
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
        typer.echo(f"Files scanned: {result.files_analyzed}", err=True)
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

    if output_dir:
        md_path, json_path, html_path = result.write(
            Path(output_dir), include_html=not no_html
        )
        typer.echo(f"Markdown:  {md_path}", err=True)
        typer.echo(f"JSON:      {json_path}", err=True)
        if html_path:
            typer.echo(f"HTML:      {html_path}", err=True)
    else:
        md_path, json_path, html_path = result.write(
            Path.cwd(), include_html=not no_html
        )
        typer.echo(f"Markdown:  {md_path}", err=True)
        typer.echo(f"JSON:      {json_path}", err=True)
        if html_path:
            typer.echo(f"HTML:      {html_path}", err=True)

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
