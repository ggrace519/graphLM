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


def usage_summary(meta: GraphMeta) -> str | None:
    """One terse clause on pass-2 token usage, or None when there is nothing to say.

    Reports the server's real prompt count beside graphlm's own estimate so a
    reader can see how far the ``estimate_tokens`` heuristic (#17) is off on
    this endpoint, plus the output size. Pass 1 is omitted from the prose (it
    is a tree-only prompt and rarely interesting); it stays in ``GRAPH.json``.
    Shared by ``GRAPH.md`` and the CLI so the wording cannot drift.
    """
    if meta.usage is None or meta.usage.pass2 is None:
        return None
    p2 = meta.usage.pass2
    prompt = (
        f"{p2.prompt_tokens} tokens"
        if p2.prompt_tokens is not None
        else "not reported by endpoint"
    )
    text = f"pass 2 prompt: {prompt} (graphlm estimated {p2.estimated_prompt_tokens})"
    if p2.completion_tokens is not None:
        text += f"; output: {p2.completion_tokens} tokens"
    return text


def faithfulness_summary(meta: GraphMeta) -> str | None:
    """One terse clause on LLM-vs-AST edge agreement, or None when not scored.

    ``n/a`` marks a ratio with no denominator (no comparable LLM edges, or no
    AST edges) — distinct from a real 0.00, which means the sides disagree.
    Shared by ``GRAPH.md`` and the CLI.
    """
    f = meta.faithfulness
    if f is None:
        return None

    def _ratio(value: float | None) -> str:
        return "n/a" if value is None else f"{value:.2f}"

    return (
        "LLM import edges vs parser ground truth: "
        f"precision {_ratio(f.precision)}, recall {_ratio(f.recall)} "
        f"(n={f.llm_edges} LLM / {f.ast_edges} AST, {f.matched} matched)"
    )


def _render_telemetry(meta: GraphMeta) -> str | None:
    """Render the run-telemetry blockquote line under the directive, or None.

    Both halves are optional (a dry run has neither; ``--no-ast`` has no
    faithfulness; an endpoint may report no usage) — whichever is present is
    shown, and the line is omitted entirely when neither is. Terse on purpose:
    this is read by agents deciding how much to trust the LLM's edge table.
    """
    parts = [
        p for p in (usage_summary(meta), faithfulness_summary(meta)) if p is not None
    ]
    if not parts:
        return None
    return "> **Run telemetry.** " + ". ".join(parts) + "."


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
        telemetry = _render_telemetry(graph.meta)
        if telemetry is not None:
            lines.append(telemetry)
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


class WriteResult(tuple):
    """The (md, json, html) path tuple, with diff paths as extra attributes.

    Returned by ``write_outputs``. It *is* the 3-tuple existing callers unpack —
    ``md, json_, html = write_outputs(...)`` still works — so the diff feature
    did not churn the arity every call site depends on (ADR-002 consequence:
    "do not silently change the arity the existing callers unpack"). The diff
    paths are read off the attributes instead:

        result = write_outputs(...)
        result.diff_md    # Path | None
        result.diff_json  # Path | None
    """

    diff_md: Path | None
    diff_json: Path | None

    def __new__(
        cls,
        md: Path | tuple,
        json_: Path | None = None,
        html: Path | None = None,
        *,
        diff_md: Path | None = None,
        diff_json: Path | None = None,
    ) -> "WriteResult":
        # Accept EITHER three positional path args (the normal construction) OR a
        # single 3-sequence. copy/deepcopy/pickle reconstruct a tuple subclass by
        # calling cls(<the 3-tuple>) — one iterable arg — so without this branch
        # every copy/pickle of a WriteResult would raise "missing 2 required
        # positional arguments". __getnewargs_ex__ below carries the diff attrs
        # through that round-trip.
        if json_ is None and html is None and isinstance(md, (tuple, list)):
            md, json_, html = md  # type: ignore[misc]
        self = super().__new__(cls, (md, json_, html))
        self.diff_md = diff_md
        self.diff_json = diff_json
        return self

    def __getnewargs_ex__(self) -> tuple[tuple, dict]:
        """Preserve the diff attributes across copy / deepcopy / pickle.

        The default ``tuple.__getnewargs__`` returns only the three elements, so
        a reconstructed ``WriteResult`` would lose ``diff_md`` / ``diff_json``.
        This returns them as keyword args to ``__new__``.
        """
        return (tuple(self), {"diff_md": self.diff_md, "diff_json": self.diff_json})


def write_outputs(
    graph: CodebaseGraph,
    output_dir: Path,
    *,
    md_suffix: str = "GRAPH",
    json_suffix: str = "GRAPH",
    html: bool = True,
    html_suffix: str = "GRAPH",
    diff: bool = True,
    diff_suffix: str | None = None,
) -> WriteResult:
    """Write Markdown, JSON, optionally HTML, and (by default) the diff to output_dir.

    The graph-vs-graph diff (``GRAPH_DIFF.md`` + ``.json``) reads the *prior*
    ``{json_suffix}.json`` in ``output_dir`` — before it is overwritten — and
    reports what changed in the map (ADR-002). ``diff=False`` skips it.

    ``diff_suffix`` defaults to **following ``json_suffix``** (ADR-002 decision
    6: the diff tracks the graph's suffix, so ``json_suffix="map"`` yields
    ``map_DIFF.*`` — the same base the baseline was read from). Pass an explicit
    ``diff_suffix`` to override.

    Returns:
        A ``WriteResult`` — the ``(md_path, json_path, html_path_or_None)``
        tuple, with ``.diff_md`` / ``.diff_json`` attributes (``None`` when
        ``diff=False``).
    """
    if diff_suffix is None:
        diff_suffix = json_suffix
    from graphlm.diff import (
        compute_diff,
        load_baseline,
        render_diff_json,
        render_diff_markdown,
    )

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    md_path = output_dir / f"{md_suffix}.md"
    json_path = output_dir / f"{json_suffix}.json"

    # Read the prior graph BEFORE overwriting GRAPH.json (ADR-002 decision 1 —
    # ordering: baseline read must precede the write).
    old_graph = None
    baseline_state = None
    if diff:
        old_graph, baseline_state = load_baseline(json_path)

    md_path.write_text(render_markdown(graph), encoding="utf-8")
    json_path.write_bytes(render_json(graph))

    html_path: Path | None = None
    if html:
        html_path = output_dir / f"{html_suffix}.html"
        html_path.write_text(_render_html(graph), encoding="utf-8")

    diff_md_path: Path | None = None
    diff_json_path: Path | None = None
    if diff:
        assert baseline_state is not None
        graph_diff = compute_diff(old_graph, graph, baseline_state)
        diff_md_path = output_dir / f"{diff_suffix}_DIFF.md"
        diff_json_path = output_dir / f"{diff_suffix}_DIFF.json"
        diff_md_path.write_text(render_diff_markdown(graph_diff), encoding="utf-8")
        diff_json_path.write_bytes(render_diff_json(graph_diff))

    return WriteResult(
        md_path,
        json_path,
        html_path,
        diff_md=diff_md_path,
        diff_json=diff_json_path,
    )
