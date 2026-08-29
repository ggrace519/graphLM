"""Output rendering — convert CodebaseGraph to Markdown and JSON."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

from graphlm.models import CodebaseGraph


def render_markdown(graph: CodebaseGraph) -> str:
    """Render a CodebaseGraph as a Markdown document."""
    lines: list[str] = []

    # Header
    lines.append("# Codebase Graph\n")
    lines.append(
        "This file was generated automatically by graphLM. "
        "Use it as a map of the project structure without reading every file.\n"
    )

    # Directory tree
    lines.append("## Directory Tree\n")
    lines.append("```\n")
    lines.append(graph.directory_tree)
    lines.append("\n```\n")

    # Import edges
    if graph.import_edges:
        lines.append("## Import Edges\n")
        lines.append("| From | To | Kind |")
        lines.append("|------|-----|------|")
        for edge in sorted(graph.import_edges, key=lambda e: (e.from_path, e.to_path)):
            lines.append(f"| `{edge.from_path}` | `{edge.to_path}` | {edge.kind} |")
        lines.append("")

    # Modules
    if graph.modules:
        lines.append("## Modules\n")
        lines.append("| Path | Name | Description |")
        lines.append("|------|------|-------------|")
        for mod in sorted(graph.modules, key=lambda m: m.path):
            lines.append(f"| `{mod.path}` | {mod.name} | {mod.description} |")
        lines.append("")

    # Data flow
    if graph.data_flow:
        lines.append("## Data Flow\n")
        lines.append("| Source | Destination | Description |")
        lines.append("|--------|-------------|-------------|")
        for flow in graph.data_flow:
            lines.append(f"| {flow.source} | {flow.destination} | {flow.description} |")
        lines.append("")

    # Database schema
    if graph.database_schema:
        lines.append("## Database Schema\n")
        for table in graph.database_schema:
            lines.append(f"### `{table.name}`")
            lines.append(f"*{table.description}*\n")
            lines.append("| Column | Type | Constraints |")
            lines.append("|--------|------|-------------|")
            for col in table.columns:
                lines.append(
                    f"| `{col.name}` | {col.type} | {col.constraints or '-'} |"
                )
            lines.append("")

    # Test organization
    if graph.test_organization:
        lines.append("## Test Organization\n")
        lines.append("| Test File | Covers |")
        lines.append("|-----------|--------|")
        for test in sorted(graph.test_organization, key=lambda t: t.file):
            lines.append(f"| `{test.file}` | {test.covers} |")
        lines.append("")

    # Architecture notes
    if graph.architecture_notes:
        lines.append("## Architecture Notes\n")
        for note in graph.architecture_notes:
            lines.append(f"- {note.note}")
        lines.append("")

    # File summaries
    if graph.file_summaries:
        lines.append("## File Summaries\n")
        for fs in sorted(graph.file_summaries, key=lambda f: f.path):
            lines.append(f"### `{fs.path}`")
            lines.append(f"{fs.summary}\n")
            if fs.symbols:
                lines.append("| Symbol | Type | Description |")
                lines.append("|--------|------|-------------|")
                for sym in sorted(fs.symbols, key=lambda s: s.name):
                    lines.append(f"| `{sym.name}` | {sym.kind} | {sym.description} |")
                lines.append("")

    # Entry points
    if graph.entry_points:
        lines.append("## Entry Points\n")
        lines.append("| File | Name | Type | Description |")
        lines.append("|------|------|------|-------------|")
        for ep in sorted(graph.entry_points, key=lambda e: (e.path, e.name)):
            lines.append(f"| `{ep.path}` | `{ep.name}` | {ep.kind} | {ep.description} |")
        lines.append("")

    # Quick reference
    if graph.quick_reference:
        lines.append("## Quick Reference\n")
        lines.append("| Find | Location |")
        lines.append("|------|----------|")
        for ref in sorted(graph.quick_reference, key=lambda r: r.query):
            lines.append(f"| {ref.query} | `{ref.location}` |")
        lines.append("")

    return "\n".join(lines) + "\n"


def render_json(graph: CodebaseGraph) -> bytes:
    """Serialize a CodebaseGraph to JSON bytes."""
    return json.dumps(
        graph.model_dump(exclude_none=True, by_alias=True),
        indent=2,
        ensure_ascii=False,
    ).encode("utf-8")


def write_outputs(
    graph: CodebaseGraph,
    output_dir: Path,
    *,
    md_suffix: str = "graphs",
    json_suffix: str = "graphs",
) -> tuple[Path, Path]:
    """Write Markdown and JSON outputs to output_dir.

    Returns:
        Tuple of (md_path, json_path).
    """
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    md_path = output_dir / f"{md_suffix}.md"
    json_path = output_dir / f"{json_suffix}.json"

    md_path.write_text(render_markdown(graph), encoding="utf-8")
    json_path.write_bytes(render_json(graph))

    return md_path, json_path
