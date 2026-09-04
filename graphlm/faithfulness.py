"""LLM-vs-AST faithfulness score — how much of the model's edge list the parser
can vouch for (innovation #6).

Pure computation over two edge lists already on the graph; no I/O, no LLM
call. The AST edges are the "do not contradict" ground truth injected into
the pass-2 prompt, so the LLM's ``import_edges`` *should* reproduce them; this
module measures whether it did. A low precision means the model invented
edges the parser can't see; a low recall means it dropped edges it was told
about. Both are stamped into ``meta.faithfulness`` so a reading agent can
weight the LLM's edge table accordingly.

Only edges the parser could have seen are scored on the LLM side:

* both endpoints must share an extension the AST actually produced edges
  for (``.py`` is always eligible — it is the core language; ``.js`` /
  ``.jsx`` / ``.ts`` / ``.tsx`` join in when the ``[js]`` pack emitted any
  of those edges; ``.cs`` when ``[csharp]`` did). A correct LLM edge between
  two ``.ts`` files is therefore *not* a false positive on a JS-only run
  with the extra absent, and *is* scored once the pack is installed; and
* ``kind`` must be ``import``, ``from``, ``require``, ``static``, or
  ``include`` — the model's ``register`` / ``uses`` kinds describe
  relationships the parser never claims.

Comparison is on ``(from_path, to_path)`` only; ``kind`` is ignored because
the parser and the model don't always agree on ``import`` vs ``from`` for the
same statement, and that distinction carries no dependency information.
"""

from __future__ import annotations

from collections.abc import Iterable

from graphlm.models import Faithfulness, ImportEdge

# LLM edge kinds that assert a plain module dependency — the kinds the AST
# parser emits, so the only kinds it can confirm or deny.
_COMPARABLE_KINDS = frozenset({"import", "from", "require", "static", "include"})
_PY_EXT = ".py"


def _norm(path: str) -> str:
    """Normalise a path for comparison: forward slashes, no leading ``./``.

    The parser emits POSIX-relative paths; the model sometimes echoes a
    ``./``-prefixed or backslashed form of the same file. Anything stricter
    (case folding, resolving ``..``) risks conflating distinct files.
    """
    path = path.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def _pairs(edges: Iterable[ImportEdge]) -> set[tuple[str, str]]:
    return {(_norm(e.from_path), _norm(e.to_path)) for e in edges}


def _ext(path: str) -> str:
    name = _norm(path)
    i = name.rfind(".")
    return name[i:].lower() if i != -1 else ""


def _comparable(edge: ImportEdge, ast_exts: frozenset[str]) -> bool:
    """True if the AST could have produced this LLM edge (see module docstring)."""
    return (
        edge.kind in _COMPARABLE_KINDS
        and _ext(edge.from_path) in ast_exts
        and _ext(edge.to_path) in ast_exts
    )


def score(
    llm_edges: Iterable[ImportEdge], ast_edges: list[ImportEdge] | None
) -> Faithfulness | None:
    """Score the LLM's ``import_edges`` against the AST ``deterministic_edges``.

    Returns ``None`` when ``ast_edges is None`` (AST off — there is no ground
    truth, and "not scored" must not read as "scored zero"). ``[]`` is a real
    answer (the parser ran and found nothing) and *is* scored: recall is then
    ``None`` (no denominator) and precision is 0.0 for any comparable LLM edge.

    ``precision`` = matched / comparable LLM edges, ``recall`` = matched / AST
    edges — each ``None`` when its denominator is zero rather than a fake 0 or
    1. Duplicates are collapsed on both sides (a set comparison), so the counts
    are of distinct ``(from, to)`` pairs.
    """
    if ast_edges is None:
        return None

    ast_exts = {_PY_EXT}
    for edge in ast_edges:
        ast_exts.add(_ext(edge.from_path))
        ast_exts.add(_ext(edge.to_path))
    ast_exts.discard("")
    comparable_exts = frozenset(ast_exts)

    llm_pairs = _pairs(e for e in llm_edges if _comparable(e, comparable_exts))
    ast_pairs = _pairs(ast_edges)
    matched = len(llm_pairs & ast_pairs)

    return Faithfulness(
        precision=matched / len(llm_pairs) if llm_pairs else None,
        recall=matched / len(ast_pairs) if ast_pairs else None,
        llm_edges=len(llm_pairs),
        ast_edges=len(ast_pairs),
        matched=matched,
    )
