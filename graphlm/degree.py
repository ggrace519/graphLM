"""Import fan-in (blast-radius) computation shared by the map's renderers.

A file's *fan-in* is the number of distinct other files that import it — its
blast radius: change it and every importer is potentially affected. This is a
structural signal only; it is deliberately **not** "importance" (a heavily
imported constants leaf has high fan-in but low architectural weight — see
ADR-015). Both ``query.overview`` (MCP) and the ``GRAPH.md`` orientation block
rank by this, so it lives here as one definition over a ``CodebaseGraph`` rather
than being recomputed against the query layer's ``MapIndex``.
"""

from __future__ import annotations

from graphlm.models import CodebaseGraph, ImportEdge
from graphlm.pathnorm import norm_path as _norm


def fan_in(graph: CodebaseGraph) -> dict[str, int]:
    """Map each imported file → count of *distinct* files that import it.

    Edges are the union of the parser's ``deterministic_edges`` (ground truth)
    and the LLM's ``import_edges``; a file that both ``import x`` and
    ``from x import y`` counts its importer once (distinct importing files, not
    edge rows).
    """
    importers: dict[str, set[str]] = {}
    edges: list[ImportEdge] = [
        *(graph.deterministic_edges or []),
        *graph.import_edges,
    ]
    for e in edges:
        src, dst = _norm(e.from_path), _norm(e.to_path)
        if src == dst:
            continue
        importers.setdefault(dst, set()).add(src)
    return {dst: len(srcs) for dst, srcs in importers.items()}


def top_fan_in(graph: CodebaseGraph, limit: int = 5) -> list[tuple[str, int]]:
    """The ``limit`` most-imported files as ``(path, importer_count)``.

    Sorted by descending count, then path for a stable, deterministic order.
    Files imported by nothing are omitted. Returns ``[]`` when there are no
    edges.
    """
    counts = fan_in(graph)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return ranked[:limit]
