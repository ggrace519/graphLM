"""Import cycle detection using Tarjan's strongly-connected-components algorithm."""

from __future__ import annotations

import math
from collections import defaultdict

from graphlm.models import Cycle, ImportEdge
from graphlm.scanner import FileFragment


def _tarjan_scc(nodes: set[str], adj: dict[str, set[str]]) -> list[list[str]]:
    """Tarjan's algorithm for strongly connected components.

    Returns a list of SCCs, each SCC being a list of node labels.
    """
    index_counter = [0]
    stack: list[str] = []
    on_stack: set[str] = set()
    index_map: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    sccs: list[list[str]] = []

    def strongconnect(v: str) -> None:
        index_map[v] = index_counter[0]
        lowlink[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack.add(v)

        for w in adj.get(v, set()):
            if w not in index_map:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in on_stack:
                lowlink[v] = min(lowlink[v], index_map[w])

        if lowlink[v] == index_map[v]:
            scc: list[str] = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                scc.append(w)
                if w == v:
                    break
            sccs.append(scc)

    for node in nodes:
        if node not in index_map:
            strongconnect(node)

    return sccs


def _build_adjacency(
    edges: list[ImportEdge],
) -> tuple[set[str], dict[str, set[str]]]:
    """Build node set and adjacency list from import edges."""
    nodes: set[str] = set()
    adj: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        nodes.add(edge.from_path)
        nodes.add(edge.to_path)
        adj[edge.from_path].add(edge.to_path)
    return nodes, adj


def _find_edges_in_scc(
    nodes: list[str], edges: list[ImportEdge]
) -> list[ImportEdge]:
    """Return only edges where both endpoints are in the SCC."""
    node_set = set(nodes)
    return [e for e in edges if e.from_path in node_set and e.to_path in node_set]


def _compute_risk_score(
    nodes: list[str], sloc_map: dict[str, int] | None,
) -> float:
    """Risk score = log10(sum SLOC) * cycle_length.

    If sloc_map is None, use 1 line per node.
    """
    length = len(nodes)
    if sloc_map is not None:
        total_sloc = sum(sloc_map.get(n, 0) for n in nodes)
    else:
        total_sloc = length  # 1 line per node
    if total_sloc <= 0:
        return 0.0
    return math.log10(total_sloc) * length


def detect_cycles(
    edges: list[ImportEdge], sloc_map: dict[str, int] | None = None,
) -> list[Cycle]:
    """Detect import cycles in a set of edges using Tarjan's SCC algorithm.

    Self-loops (single-node SCCs) are excluded -- only cycles with length > 1
    are reported.

    Args:
        edges: List of import/dependency edges.
        sloc_map: Optional mapping of file path to line count for risk scoring.

    Returns:
        List of Cycle objects sorted by risk_score descending.
    """
    if not edges:
        return []

    nodes, adj = _build_adjacency(edges)
    sccs = _tarjan_scc(nodes, adj)

    cycles: list[Cycle] = []
    for scc in sccs:
        if len(scc) <= 1:
            continue
        scc_edges = _find_edges_in_scc(scc, edges)
        risk = _compute_risk_score(scc, sloc_map)
        cycles.append(
            Cycle(
                nodes=sorted(scc),
                edges=scc_edges,
                length=len(scc),
                risk_score=risk,
            )
        )

    return sorted(cycles, key=lambda c: c.risk_score, reverse=True)


def compute_sloc_map(fragments: list[FileFragment]) -> dict[str, int]:
    """Compute a mapping of file path to line count from file fragments.

    Args:
        fragments: List of FileFragment objects with content.

    Returns:
        Dict mapping relative file path to number of lines.
    """
    sloc_map: dict[str, int] = {}
    for frag in fragments:
        sloc_map[frag.rel_path] = frag.content.count("\n") + 1
    return sloc_map
