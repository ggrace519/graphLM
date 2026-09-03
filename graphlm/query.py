"""Queries over a generated codebase map — the logic behind ``graphlm --serve``.

Pure functions over an already-materialized ``CodebaseGraph``: no LLM, no
network, no MCP dependency. ``graphlm/mcp_server.py`` is a thin transport
wrapper around these so the agent-facing tools stay unit-testable without the
``mcp`` extra installed, and so the (fast-moving) MCP SDK surface is disposable.

Why this exists: the map's primary consumer is a coding agent, and a flat
``GRAPH.md`` makes it pay for the whole document (tens of thousands of tokens)
to answer "who imports X?". Every function here answers one such question with
a few hundred tokens of structured output instead.

Edges are unified from both sources the graph carries: the parser-extracted
``deterministic_edges`` (ground truth) and the LLM's ``import_edges``. Each
neighbor row says which source(s) claimed it (``ast`` / ``llm`` / ``both``) so
an agent can weight parser-proven edges over inferred ones.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from graphlm.models import CodebaseGraph, ImportEdge


class MapUnavailable(Exception):
    """No readable map at the expected location (missing or uncomparable)."""


def _norm(path: str) -> str:
    """Canonical map path: forward slashes, no leading ``./``."""
    p = path.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


@dataclass(frozen=True, slots=True)
class EdgeRef:
    """One neighbor of a node: the other endpoint, the edge kind, its source."""

    path: str
    kind: str
    source: str  # "ast" | "llm" | "both"


@dataclass(frozen=True, slots=True)
class MapIndex:
    """Adjacency and lookup tables built once from a graph.

    Built by :func:`build_index`. Everything is keyed by canonical path.
    """

    graph: CodebaseGraph
    out_edges: dict[str, list[EdgeRef]] = field(default_factory=dict)
    in_edges: dict[str, list[EdgeRef]] = field(default_factory=dict)
    cycle_of: dict[str, list[int]] = field(default_factory=dict)  # path -> cycle idx
    known_paths: set[str] = field(default_factory=set)


def _merge_edges(
    ast_edges: Optional[list[ImportEdge]], llm_edges: list[ImportEdge]
) -> dict[tuple[str, str, str], str]:
    """Unify both edge lists into ``(from, to, kind) -> source``.

    The parser and the LLM label the same relationship with the same kinds
    (``import`` / ``from``), so a pair claimed by both collapses to one row
    tagged ``both``. LLM-only kinds (``register`` / ``include`` / ``uses``)
    never collide and stay ``llm``.
    """
    merged: dict[tuple[str, str, str], str] = {}
    for e in ast_edges or []:
        merged[(_norm(e.from_path), _norm(e.to_path), e.kind)] = "ast"
    for e in llm_edges:
        key = (_norm(e.from_path), _norm(e.to_path), e.kind)
        merged[key] = "both" if key in merged else "llm"
    return merged


def build_index(graph: CodebaseGraph) -> MapIndex:
    """Build the adjacency/lookup index for ``graph``.

    Neighbor lists are sorted (by path, then kind) so every query is
    deterministic regardless of the order the LLM emitted edges in.
    """
    out_edges: dict[str, list[EdgeRef]] = {}
    in_edges: dict[str, list[EdgeRef]] = {}
    known: set[str] = set()

    for (src, dst, kind), source in _merge_edges(
        graph.deterministic_edges, graph.import_edges
    ).items():
        out_edges.setdefault(src, []).append(EdgeRef(dst, kind, source))
        in_edges.setdefault(dst, []).append(EdgeRef(src, kind, source))
        known.add(src)
        known.add(dst)
    for lst in out_edges.values():
        lst.sort(key=lambda r: (r.path, r.kind))
    for lst in in_edges.values():
        lst.sort(key=lambda r: (r.path, r.kind))

    cycle_of: dict[str, list[int]] = {}
    for i, cycle in enumerate(graph.import_cycles):
        for node in cycle.nodes:
            cycle_of.setdefault(_norm(node), []).append(i)

    for m in graph.modules:
        known.add(_norm(m.path))
    for fs in graph.file_summaries:
        known.add(_norm(fs.path))
    for ep in graph.entry_points:
        known.add(_norm(ep.path))

    return MapIndex(
        graph=graph,
        out_edges=out_edges,
        in_edges=in_edges,
        cycle_of=cycle_of,
        known_paths=known,
    )


# --- Path resolution -------------------------------------------------------


def resolve_path(index: MapIndex, path: str) -> tuple[Optional[str], list[str]]:
    """Map a user-supplied path onto a known map path.

    Returns ``(match, candidates)``: an exact (or unique suffix/substring)
    match, or ``None`` plus the candidate list when the query is ambiguous or
    unknown. Suffix match first so ``cli.py`` finds ``graphlm/cli.py`` even in
    a repo that also has ``tests/test_cli.py``.
    """
    q = _norm(path)
    if q in index.known_paths:
        return q, []
    suffix = [p for p in sorted(index.known_paths) if p.endswith("/" + q) or p == q]
    if len(suffix) == 1:
        return suffix[0], []
    if suffix:
        return None, suffix
    lowered = q.lower()
    contains = [p for p in sorted(index.known_paths) if lowered in p.lower()]
    if len(contains) == 1:
        return contains[0], []
    return None, contains[:20]


def _unresolved(path: str, candidates: list[str]) -> dict[str, Any]:
    return {
        "path": path,
        "found": False,
        "candidates": candidates,
        "hint": (
            "no such path in the map"
            if not candidates
            else "ambiguous — pass one of the candidates"
        ),
    }


# --- Queries ---------------------------------------------------------------


def overview(index: MapIndex) -> dict[str, Any]:
    """Counts, provenance, hubs, and the architecture notes — the 30-second tour."""
    g = index.graph
    in_degree = {p: len(v) for p, v in index.in_edges.items()}
    hubs = sorted(in_degree.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    meta = g.meta.model_dump() if g.meta is not None else None
    return {
        "meta": meta,
        "counts": {
            "modules": len(g.modules),
            "file_summaries": len(g.file_summaries),
            "entry_points": len(g.entry_points),
            "llm_import_edges": len(g.import_edges),
            "ast_import_edges": (
                None if g.deterministic_edges is None else len(g.deterministic_edges)
            ),
            "data_flows": len(g.data_flow),
            "import_cycles": len(g.import_cycles),
            "quick_reference": len(g.quick_reference),
            "database_tables": (
                None if g.database_schema is None else len(g.database_schema)
            ),
        },
        "most_imported": [{"path": p, "imported_by": n} for p, n in hubs],
        "entry_points": [
            {"path": _norm(e.path), "name": e.name, "kind": e.kind}
            for e in sorted(g.entry_points, key=lambda e: (e.path, e.name))
        ],
        "architecture_notes": [n.note for n in g.architecture_notes],
    }


def module_info(index: MapIndex, path: str) -> dict[str, Any]:
    """Everything the map knows about one file/module path."""
    match, candidates = resolve_path(index, path)
    if match is None:
        return _unresolved(path, candidates)
    g = index.graph
    modules = [m for m in g.modules if _norm(m.path) == match]
    summaries = [fs for fs in g.file_summaries if _norm(fs.path) == match]
    entries = [e for e in g.entry_points if _norm(e.path) == match]
    refs = [r for r in g.quick_reference if match in _norm(r.location)]
    return {
        "path": match,
        "found": True,
        "module": (
            {"name": modules[0].name, "description": modules[0].description}
            if modules
            else None
        ),
        "summary": summaries[0].summary if summaries else None,
        "symbols": [
            {"name": s.name, "kind": s.kind, "description": s.description}
            for fs in summaries
            for s in fs.symbols
        ],
        "entry_points": [
            {"name": e.name, "kind": e.kind, "description": e.description}
            for e in entries
        ],
        "imports": len(index.out_edges.get(match, [])),
        "imported_by": len(index.in_edges.get(match, [])),
        "in_cycles": index.cycle_of.get(match, []),
        "quick_reference": [{"query": r.query, "location": r.location} for r in refs],
    }


def neighbors(index: MapIndex, path: str, direction: str = "both") -> dict[str, Any]:
    """Direct import neighbors: what ``path`` imports and what imports it."""
    if direction not in ("both", "out", "in"):
        raise ValueError("direction must be 'both', 'out', or 'in'")
    match, candidates = resolve_path(index, path)
    if match is None:
        return _unresolved(path, candidates)

    def rows(refs: list[EdgeRef]) -> list[dict[str, str]]:
        return [{"path": r.path, "kind": r.kind, "source": r.source} for r in refs]

    result: dict[str, Any] = {"path": match, "found": True}
    if direction in ("both", "out"):
        result["imports"] = rows(index.out_edges.get(match, []))
    if direction in ("both", "in"):
        result["imported_by"] = rows(index.in_edges.get(match, []))
    return result


def dependents(
    index: MapIndex, path: str, *, transitive: bool = False, limit: int = 200
) -> dict[str, Any]:
    """Files that would be affected by a change to ``path`` (blast radius).

    Direct importers by default; ``transitive=True`` walks importers-of-
    importers breadth-first, reporting each file once with its shortest
    distance. Cycles are handled by the visited set, so a cyclic graph
    terminates. ``limit`` caps the result so a hub like a shared ``utils``
    module cannot flood the agent's context.
    """
    match, candidates = resolve_path(index, path)
    if match is None:
        return _unresolved(path, candidates)

    found: list[dict[str, Any]] = []
    seen = {match}
    queue: deque[tuple[str, int]] = deque([(match, 0)])
    truncated = False
    while queue:
        node, depth = queue.popleft()
        for ref in index.in_edges.get(node, []):
            if ref.path in seen:
                continue
            seen.add(ref.path)
            if len(found) >= limit:
                truncated = True
                queue.clear()
                break
            found.append({"path": ref.path, "distance": depth + 1, "source": ref.source})
            if transitive:
                queue.append((ref.path, depth + 1))
    return {
        "path": match,
        "found": True,
        "transitive": transitive,
        "dependents": found,
        "count": len(found),
        "truncated": truncated,
    }


# Question filler an agent naturally types ("where is the X?"). Dropped before
# scoring — otherwise every quick-reference entry (they all start "Where is…")
# matches every query and outranks the real hit.
_STOPWORDS = frozenset(
    "a an and are as at by do does find for from how i in is it of on or the "
    "this to what where which who".split()
)


def _tokens(query: str) -> list[str]:
    return [t for t in query.lower().replace("?", " ").split() if t and t not in _STOPWORDS]


def _score(query_tokens: list[str], *texts: str) -> int:
    """Rank a hit: exact-token matches outweigh prefix/substring matches.

    Small integer score so ties are broken deterministically by path in the
    caller; not a relevance model, just enough to put ``secret redaction``
    on ``_redact_secrets`` (prefix match ``redact`` ↔ ``redaction``) above a
    file that happens to contain the letters ``cli``.
    """
    hay = " ".join(t.lower() for t in texts if t)
    words = set(hay.replace("/", " ").replace(".", " ").replace("_", " ").split())
    score = 0
    for tok in query_tokens:
        if tok in words:
            score += 3
        elif len(tok) >= 4 and any(
            (w.startswith(tok) or tok.startswith(w)) and len(w) >= 4 for w in words
        ):
            score += 2
        elif tok in hay:
            score += 1
    return score


def find(index: MapIndex, query: str, limit: int = 20) -> dict[str, Any]:
    """Search the map for a phrase: quick-reference, modules, symbols, summaries.

    Answers "where is X?" from the LLM-curated sections instead of grepping the
    tree. Returns ranked hits with a ``kind`` so an agent knows what it found.
    """
    tokens = _tokens(query)
    if not tokens:
        return {"query": query, "hits": []}
    g = index.graph
    hits: list[tuple[int, str, dict[str, Any]]] = []

    for r in g.quick_reference:
        s = _score(tokens, r.query, r.location)
        if s:
            hits.append((s + 2, r.location, {"kind": "quick_reference", "query": r.query, "location": r.location}))
    for m in g.modules:
        s = _score(tokens, m.path, m.name, m.description)
        if s:
            hits.append((s, m.path, {"kind": "module", "path": _norm(m.path), "name": m.name, "description": m.description}))
    for e in g.entry_points:
        s = _score(tokens, e.path, e.name, e.description)
        if s:
            hits.append((s, e.path, {"kind": "entry_point", "path": _norm(e.path), "name": e.name, "description": e.description}))
    for fs in g.file_summaries:
        for sym in fs.symbols:
            s = _score(tokens, sym.name, sym.description)
            if s:
                hits.append((s, fs.path, {"kind": "symbol", "path": _norm(fs.path), "name": sym.name, "symbol_kind": sym.kind, "description": sym.description}))
        s = _score(tokens, fs.path, fs.summary)
        if s:
            hits.append((s - 1, fs.path, {"kind": "file_summary", "path": _norm(fs.path), "summary": fs.summary}))

    hits.sort(key=lambda h: (-h[0], h[1]))
    return {"query": query, "hits": [h[2] for h in hits[:limit]], "total": len(hits)}


def cycles(index: MapIndex) -> dict[str, Any]:
    """Import cycles with risk scores, highest risk first."""
    ordered = sorted(index.graph.import_cycles, key=lambda c: -c.risk_score)
    return {
        "count": len(ordered),
        "cycles": [
            {
                "nodes": [_norm(n) for n in c.nodes],
                "length": c.length,
                "risk_score": round(c.risk_score, 2),
            }
            for c in ordered
        ],
    }


def entry_points(index: MapIndex) -> dict[str, Any]:
    """Every known entry point (main, routes, CLI commands, hooks, factories)."""
    return {
        "entry_points": [
            {"path": _norm(e.path), "name": e.name, "kind": e.kind, "description": e.description}
            for e in sorted(index.graph.entry_points, key=lambda e: (e.path, e.name))
        ]
    }


def staleness(index: MapIndex, project_dir: Path) -> dict[str, Any]:
    """Compare the stamped commit to the repo's current ``HEAD``.

    Mirrors the refresh directive in ``GRAPH.md`` (ADR-001): ``stale`` means
    ``HEAD`` moved since generation; ``unknown`` means one side has no SHA (a
    non-git project or an old, meta-less map). Advisory either way — the map
    is built from the working tree, so it can be SHA-fresh yet not match
    uncommitted edits.
    """
    from graphlm.provenance import git_commit_sha

    meta = index.graph.meta
    stamped = meta.commit_sha if meta is not None else None
    head = git_commit_sha(project_dir)
    if stamped is None or head is None:
        state = "unknown"
    elif stamped == head:
        state = "fresh"
    else:
        state = "stale"
    return {
        "state": state,
        "generated_against": stamped,
        "head": head,
        "generated_at": meta.created_at if meta is not None else None,
        "hint": "regenerate with `graphlm .` from the project root" if state != "fresh" else None,
    }


# --- Loading ---------------------------------------------------------------


def load_map(json_path: Path) -> CodebaseGraph:
    """Read a ``GRAPH.json`` for querying, or raise :class:`MapUnavailable`.

    Reuses ``diff.load_baseline`` — the one reader that already classifies a
    missing vs corrupt vs unknown-version file (ADR-002 decision 4) — so the
    server gives the same honest answer the diff would.
    """
    from graphlm.diff import BaselineState, load_baseline

    graph, state = load_baseline(json_path)
    if state is BaselineState.UNCOMPARABLE:
        raise MapUnavailable(
            f"map at {json_path} could not be read (corrupt or unknown "
            "schema_version) — regenerate with `graphlm .`"
        )
    if state is BaselineState.FIRST_RUN or graph is None:
        raise MapUnavailable(
            f"no map at {json_path} — run `graphlm .` from the project root first"
        )
    return graph
