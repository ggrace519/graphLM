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


def _build_nodes(graph: CodebaseGraph) -> list[dict[str, Any]]:
    """Build D3 node data from the graph."""
    nodes: list[dict[str, Any]] = []

    for mod in graph.modules:
        nodes.append({
            "name": mod.name,
            "type": "module",
            "path": mod.path,
            "description": mod.description,
            "r": 8,
            "color": _directory_color(mod.path),
        })

    for ep in graph.entry_points:
        nodes.append({
            "name": ep.name,
            "type": "entry_point",
            "path": ep.path,
            "description": ep.description,
            "r": 12,
            "color": _directory_color(ep.path),
        })

    for fs in graph.file_summaries:
        nodes.append({
            "name": fs.path,
            "type": "file_summary",
            "path": fs.path,
            "description": fs.summary,
            "r": 5,
            "color": _directory_color(fs.path),
        })

    return nodes


def _build_links(graph: CodebaseGraph) -> list[dict[str, Any]]:
    """Build D3 link data from the graph."""
    links: list[dict[str, Any]] = []

    for edge in graph.import_edges:
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
    data = json.dumps(
        {"nodes": _build_nodes(graph), "links": _build_links(graph)},
        ensure_ascii=False,
    )
    palette_js = json.dumps(_PALETTE, ensure_ascii=False)
    tpl = _load_template()
    result = tpl.replace("{EMBEDDED_JSON}", data, 1)
    result = result.replace("{_PALETTE}", palette_js, 1)
    return result
