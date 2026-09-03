"""Interactive HTML visualization for codebase graphs using D3.js."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from graphlm.models import CodebaseGraph

# Deterministic color palette for directory hashing
_PALETTE: list[str] = [
    "#e6194b", "#3cb44b", "#ffe119", "#4363d8", "#f58231",
    "#911eb4", "#42d4f4", "#f032e6", "#bfef45", "#fabed4",
    "#469990", "#dcbeff", "#9A6324", "#fffac8", "#800000",
    "#aaffc3", "#808000", "#ffd8b1", "#000075", "#a9a9a9",
]


def _directory_color(dir_name: str) -> str:
    """Return a deterministic color from the palette based on a directory name."""
    idx = int(hashlib.md5(dir_name.encode()).hexdigest(), 16) % len(_PALETTE)
    return _PALETTE[idx]


_TYPE_RANK = {
    "entry_point": 3,
    "module": 2,
    "file_summary": 1,
    "file": 0,
    "component": 0,
}


def _upsert_node(
    by_id: dict[str, dict[str, Any]],
    key: str,
    *,
    name: str,
    type: str,
    path: str,
    description: str,
    r: int,
) -> None:
    """Insert or merge a node. One node per id so D3 forceLink can resolve links."""
    existing = by_id.get(key)
    if existing is None:
        by_id[key] = {
            "id": key,
            "name": name,
            "type": type,
            "path": path,
            "description": description,
            "r": r,
            "color": _directory_color(path),
        }
        return
    if _TYPE_RANK.get(type, 0) > _TYPE_RANK.get(existing["type"], 0):
        existing["type"] = type
        existing["name"] = name or existing["name"]
    if r > existing["r"]:
        existing["r"] = r
    if description and (
        not existing["description"] or len(description) > len(existing["description"])
    ):
        existing["description"] = description


def _build_nodes(graph: CodebaseGraph) -> list[dict[str, Any]]:
    """Build D3 node data from the graph.

    One node per file path (or data-flow label). Import-edge (LLM *and* AST)
    and data-flow endpoints that are not already modules/entry points/summaries
    are added so every link can resolve — D3 forceLink throws on missing node
    ids. Every node carries ``in_cycle``: True when its path is a member of
    any ``import_cycles`` SCC, so the template can ring it red.
    """
    by_id: dict[str, dict[str, Any]] = {}

    for mod in graph.modules:
        _upsert_node(
            by_id,
            mod.path,
            name=mod.name,
            type="module",
            path=mod.path,
            description=mod.description,
            r=8,
        )
    for ep in graph.entry_points:
        _upsert_node(
            by_id,
            ep.path,
            name=ep.name,
            type="entry_point",
            path=ep.path,
            description=ep.description,
            r=12,
        )
    for fs in graph.file_summaries:
        _upsert_node(
            by_id,
            fs.path,
            name=fs.path,
            type="file_summary",
            path=fs.path,
            description=fs.summary,
            r=5,
        )
    for edge in [*graph.import_edges, *(graph.deterministic_edges or [])]:
        for p in (edge.from_path, edge.to_path):
            if p not in by_id:
                _upsert_node(
                    by_id, p, name=p, type="file", path=p, description="", r=6
                )
    for flow in graph.data_flow:
        for p in (flow.source, flow.destination):
            if p not in by_id:
                _upsert_node(
                    by_id,
                    p,
                    name=p,
                    type="component",
                    path=p,
                    description=flow.description,
                    r=7,
                )

    cycle_paths = {node for cycle in graph.import_cycles for node in cycle.nodes}
    for node in by_id.values():
        node["in_cycle"] = node["path"] in cycle_paths

    return list(by_id.values())


def _build_links(graph: CodebaseGraph) -> list[dict[str, Any]]:
    """Build D3 link data from the graph.

    Three link types, so the picture distinguishes parser-proven structure
    from LLM inference: ``ast`` (``deterministic_edges``, solid accent
    stroke), ``import`` (LLM ``import_edges``, grey), ``data_flow`` (dashed).
    An LLM edge with the same ``(from, to)`` as an AST edge is **dropped** and
    the AST link marked ``corroborated`` — drawing two lines between one pair
    would read as two relationships. Only the LLM-only imports survive as
    ``import`` links.
    """
    links: list[dict[str, Any]] = []

    ast_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for edge in graph.deterministic_edges or []:
        pair = (edge.from_path, edge.to_path)
        if pair in ast_by_pair:
            continue  # the parser can emit one edge per import statement
        link = {
            "source": edge.from_path,
            "target": edge.to_path,
            "type": "ast",
            "stroke": "#7aa2f7",
            "dash": None,
            "corroborated": False,
        }
        ast_by_pair[pair] = link
        links.append(link)

    for edge in graph.import_edges:
        pair = (edge.from_path, edge.to_path)
        if pair in ast_by_pair:
            ast_by_pair[pair]["corroborated"] = True
            continue
        links.append({
            "source": edge.from_path,
            "target": edge.to_path,
            "type": "import",
            "stroke": "#888",
            "dash": None,
        })

    for flow in graph.data_flow:
        links.append({
            "source": flow.source,
            "target": flow.destination,
            "type": "data_flow",
            "stroke": "#c69",
            "dash": "5,5",
        })

    return links


def _load_template() -> str:
    """Load the HTML template from the companion file."""
    _template_path = Path(__file__).parent / "_html_template.html"
    return _template_path.read_text(encoding="utf-8")


def render_html(graph: CodebaseGraph) -> str:
    """Render a CodebaseGraph as a self-contained HTML file with D3.js.

    The output is a single HTML file with inline CSS, embedded data,
    and inline JavaScript -- no external files needed (except D3 CDN).
    """
    # ``cycles`` is the SCC count for the stats line — it is not derivable
    # from the in_cycle node flags (two cycles of three nodes and one of six
    # both flag six nodes).
    data = json.dumps(
        {
            "nodes": _build_nodes(graph),
            "links": _build_links(graph),
            "cycles": len(graph.import_cycles),
        },
        ensure_ascii=False,
    )
    palette_js = json.dumps(_PALETTE, ensure_ascii=False)
    tpl = _load_template()
    result = tpl.replace("{EMBEDDED_JSON}", data, 1)
    result = result.replace("{_PALETTE}", palette_js, 1)
    return result
