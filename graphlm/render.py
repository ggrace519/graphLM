"""Output rendering — convert CodebaseGraph to Markdown, JSON, and optionally HTML."""

from __future__ import annotations

import json
from pathlib import Path

from graphlm.models import CodebaseGraph, GraphMeta


def _render_directive(meta: GraphMeta) -> str:
    """Render the top-of-file refresh directive from a provenance stamp.

    Two forms, chosen by whether a commit SHA was captured:

    * *Git form* — names the commit and date and tells a reading agent to
      compare the repo's current ``HEAD`` to it and regenerate if they differ.
    * *Non-git form* — no SHA to compare, so it falls back to the agent's own
      judgment of whether the code has changed.

    Wording note: "generated against commit X", never "reflects X". The graph
    is built from files on disk, which may include uncommitted changes, so a
    graph can be SHA-fresh yet not match the working tree; the honest phrasing
    avoids overclaiming. The command is ``graphlm .`` (run from the project
    root) — deliberately relative, so a committed GRAPH.md carries no absolute
    path and the line is copy-pasteable anywhere.
    """
    date = meta.created_at
    if meta.commit_sha:
        sha8 = meta.commit_sha[:8]
        return (
            "> **Provenance & refresh directive.** This codebase map was "
            f"generated against commit `{sha8}` on {date}.\n"
            "> Before relying on it, check whether the repo has moved on: "
            "compare the current `git rev-parse HEAD` to that commit. If they "
            "differ, the map may be out of date — regenerate it by running "
            "`graphlm .` from the project root. This is advisory; the map is "
            "best-effort, not guaranteed current."
        )
    return (
        "> **Provenance & refresh directive.** This codebase map was generated "
        f"on {date}. No git commit tracking was available, so staleness can't "
        "be checked automatically.\n"
        "> Regenerate it by running `graphlm .` from the project root whenever "
        "you believe the code has changed. This is advisory; the map is "
        "best-effort, not guaranteed current."
    )


def _render_html(graph: CodebaseGraph) -> str:
    """Render a CodebaseGraph as a self-contained HTML visualization."""
    from graphlm.html_render import render_html as _render_html_impl
    return _render_html_impl(graph)


def render_markdown(graph: CodebaseGraph) -> str:
    """Render a CodebaseGraph as a Markdown document."""
    lines: list[str] = []

    # Refresh directive (rendered from the provenance stamp, when present). Sits
    # above the heading so a reading agent meets it first. Omitted entirely when
    # there is no stamp (older format or a library caller that never set meta).
    if graph.meta is not None:
        lines.append(_render_directive(graph.meta))
        lines.append("")

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

    # Import cycles
    if graph.import_cycles:
        lines.append("## Import Cycles\n")
        for i, cycle in enumerate(
            sorted(graph.import_cycles, key=lambda c: c.risk_score, reverse=True)
        ):
            label = (
                f"*{cycle.length} nodes — mutual dependency*"
                if cycle.length == 2
                else f"*{cycle.length} nodes*"
            )
            lines.append(f"### Cycle {i+1} (risk score: {cycle.risk_score:.1f})")
            lines.append(label)
            for node in cycle.nodes:
                lines.append(f"- `{node}`")
            lines.append("")

    return "\n".join(lines) + "\n"


def render_json(graph: CodebaseGraph) -> bytes:
    """Serialize a CodebaseGraph to JSON bytes.

    ``exclude_none=True`` keeps the LLM-facing fields tidy (e.g. a null
    ``database_schema`` stays out), but it would also silently drop
    ``meta.commit_sha`` when null — making a non-git graph indistinguishable
    from an old, meta-less one in the artifact we treat as authoritative. So
    ``meta`` is re-serialized *with* its nulls and spliced back in, keeping
    ``commit_sha: null`` explicit while the rest of the graph stays pruned.
    """
    data = graph.model_dump(exclude_none=True, by_alias=True)
    if graph.meta is not None:
        data["meta"] = graph.meta.model_dump(by_alias=True)
    return json.dumps(
        data,
        indent=2,
        ensure_ascii=False,
    ).encode("utf-8")


def write_outputs(
    graph: CodebaseGraph,
    output_dir: Path,
    *,
    md_suffix: str = "GRAPH",
    json_suffix: str = "GRAPH",
    html: bool = True,
    html_suffix: str = "GRAPH",
) -> tuple[Path, Path, Path | None]:
    """Write Markdown, JSON, and optionally HTML outputs to output_dir.

    Returns:
        Tuple of (md_path, json_path, html_path_or_None).
    """
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    md_path = output_dir / f"{md_suffix}.md"
    json_path = output_dir / f"{json_suffix}.json"

    md_path.write_text(render_markdown(graph), encoding="utf-8")
    json_path.write_bytes(render_json(graph))

    html_path: Path | None = None
    if html:
        html_path = output_dir / f"{html_suffix}.html"
        html_path.write_text(_render_html(graph), encoding="utf-8")

    return md_path, json_path, html_path
