"""Mermaid module graph for ``GRAPH.md`` — a directory-level picture of the import edges.

Why a Mermaid block at all: GitHub (and most Markdown viewers) render Mermaid
fences natively, so the map gets a *picture* with no CDN, no build step, and no
separate file — unlike ``GRAPH.html``, which loads D3 from a CDN and is blank
offline. Why directory-level: a file-level graph of a real project is hundreds
of nodes and unreadable in a Markdown page; collapsing each file to its parent
directory gives a package-dependency view that fits on one screen, and the
``max_nodes`` cap bounds it further for very large trees.

Ground truth wins: when the parser's ``deterministic_edges`` are present they
are the edge source (and the note says so); the LLM's ``import_edges`` are only
the fallback for ``--no-ast`` runs, and are labelled as inferred.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable

from graphlm.models import CodebaseGraph, ImportEdge

# Red used for cycle members — the same hue as the ``in_cycle`` ring in
# ``GRAPH.html`` so the two pictures agree.
CYCLE_COLOR = "#e11"

_UNSAFE_ID_CHARS = re.compile(r"[^A-Za-z0-9_]")


def _collapse_dir(path: str) -> str:
    """Map a file path to its directory-level node label.

    ``graphlm/parsers/python.py`` -> ``graphlm/parsers``; a root-level file
    (``setup.py``) has no directory and stays its own node — collapsing every
    root file into a single ``.`` node would hide the one place (top-level
    scripts) where per-file structure still matters.
    """
    head, sep, _tail = path.rpartition("/")
    return head if sep else path


def _mermaid_label(label: str) -> str:
    """Escape a label for use inside a quoted Mermaid node label.

    Only ``"`` breaks a quoted label; Mermaid's ``#quot;`` entity restores it.
    """
    return label.replace('"', "#quot;")


def _assign_ids(labels: list[str]) -> dict[str, str]:
    """Derive a safe, unique Mermaid id for every label (in the given order).

    Mermaid ids may only contain ``[A-Za-z0-9_]``, so every other character
    becomes ``_`` and the id is prefixed ``n_`` (an id may not start with a
    digit, and ``n_`` also keeps a directory named e.g. ``end`` — a Mermaid
    keyword — from breaking the diagram). The sanitizing is lossy (``a-b`` and
    ``a_b`` collide), so a numeric suffix disambiguates a repeat; ``labels``
    must be sorted by the caller so the suffixes are stable across runs.
    """
    ids: dict[str, str] = {}
    taken: set[str] = set()
    for label in labels:
        base = "n_" + _UNSAFE_ID_CHARS.sub("_", label)
        candidate = base
        n = 2
        while candidate in taken:
            candidate = f"{base}_{n}"
            n += 1
        ids[label] = candidate
        taken.add(candidate)
    return ids


def _cycle_edge_test(graph: CodebaseGraph) -> Callable[[ImportEdge], bool]:
    """Return ``is_cycle(edge)``: True when both endpoints share an import cycle.

    Membership is decided at the *file* level, before collapsing — two files in
    the same SCC are cycle members regardless of which directories they land
    in. Cycle sets are frozensets of the SCC's node paths.
    """
    cycle_sets = [frozenset(c.nodes) for c in graph.import_cycles]

    def is_cycle(edge: ImportEdge) -> bool:
        return any(
            edge.from_path in members and edge.to_path in members
            for members in cycle_sets
        )

    return is_cycle


def render_mermaid(graph: CodebaseGraph, *, max_nodes: int = 40) -> list[str]:
    """Render the ``## Module Graph`` section lines, or ``[]`` when there are no edges.

    The block is a ``flowchart LR`` over directory-level nodes. Cycle edges are
    emitted *last* so their ``linkStyle`` indices are simply the tail of the
    link list — Mermaid indexes links by emission order and has no per-link
    id, so styling by index is the only option, and grouping the styled links
    at the end keeps the index arithmetic trivial and testable. Directories
    that contain a cycle member get a red outline: an intra-directory cycle
    (the common case — files of one package importing each other) collapses
    to a self-edge, which is dropped as noise, so without the node outline the
    picture would show no trace of it.

    Output is fully sorted (nodes by label, edges by ``(from, to)`` within the
    plain/cycle groups) so a regenerated ``GRAPH.md`` diffs cleanly.
    """
    if graph.deterministic_edges:
        edges = graph.deterministic_edges
        source_note = "*parser-extracted import edges (ground truth)*"
    elif graph.import_edges:
        edges = graph.import_edges
        source_note = "*LLM-inferred import edges*"
    else:
        return []

    is_cycle = _cycle_edge_test(graph)
    cycle_dirs = {
        _collapse_dir(node) for cycle in graph.import_cycles for node in cycle.nodes
    }

    # Collapse to directory level; a collapsed edge is a cycle edge if ANY of
    # the file-level edges behind it was one. Self-edges are dropped.
    collapsed: dict[tuple[str, str], bool] = {}
    for edge in edges:
        key = (_collapse_dir(edge.from_path), _collapse_dir(edge.to_path))
        if key[0] == key[1]:
            continue
        collapsed[key] = collapsed.get(key, False) or is_cycle(edge)

    degree: dict[str, int] = defaultdict(int)
    for src, dst in collapsed:
        degree[src] += 1
        degree[dst] += 1
    # Highest degree first; label breaks ties so the cut is deterministic.
    ranked = sorted(degree, key=lambda d: (-degree[d], d))
    hidden = len(ranked) - max_nodes if len(ranked) > max_nodes else 0
    kept = set(ranked[:max_nodes])
    nodes = sorted(kept)
    ids = _assign_ids(nodes)

    plain = sorted(
        k for k, cyc in collapsed.items()
        if not cyc and k[0] in kept and k[1] in kept
    )
    cyclic = sorted(
        k for k, cyc in collapsed.items()
        if cyc and k[0] in kept and k[1] in kept
    )
    cycle_nodes = sorted(kept & cycle_dirs)

    lines: list[str] = ["## Module Graph\n"]
    lines.append(
        f"{source_note} — directory-level view; files are collapsed to their "
        "parent directory.\n"
    )
    lines.append("```mermaid")
    lines.append("flowchart LR")
    for label in nodes:
        lines.append(f'    {ids[label]}["{_mermaid_label(label)}"]')
    for src, dst in plain + cyclic:
        lines.append(f"    {ids[src]} --> {ids[dst]}")
    if cyclic:
        first = len(plain)
        indices = ",".join(str(i) for i in range(first, first + len(cyclic)))
        lines.append(f"    linkStyle {indices} stroke:{CYCLE_COLOR},stroke-width:2px")
    for label in cycle_nodes:
        lines.append(f"    style {ids[label]} stroke:{CYCLE_COLOR},stroke-width:2px")
    lines.append("```\n")

    if cyclic:
        lines.append("Red edges are members of an import cycle.")
    if cycle_nodes:
        lines.append("Red-outlined directories contain a file in an import cycle.")
    if hidden:
        lines.append(f"*… {hidden} more directories not shown*")
    if cyclic or cycle_nodes or hidden:
        lines.append("")
    return lines
