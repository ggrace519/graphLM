"""C# Tree-sitter resolver (the ``graphlm[csharp]`` pack).

``using MyApp.Models;`` is a *namespace* import, not a type import. Fanning
it out to every ``.cs`` in that namespace would churn GRAPH_DIFF whenever a
file is added (the Java wildcard problem, ADR-005). v1 therefore:

- ``using static Ns.Type;`` and ``using Alias = Ns.Type;`` resolve to
  ``Ns/Type.cs`` (then ``Ns.cs`` for a nested type), like Java static.
- a namespace ``using Ns;`` / ``global using Ns;`` resolves only when
  **exactly one** scanned file lives in the ``Ns/`` directory (or
  ``Ns.cs`` itself). Two or more files in that directory are a policy drop
  and mark the language known-partial.
- ``using System;`` and any other FQN that misses the scan are dropped as
  third-party, not partial.

``kind`` is ``static`` for ``using static`` and ``import`` otherwise.
``source_roots`` is grammar-free (``src/`` prefixes plus ``""``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from graphlm.models import ImportEdge
from graphlm.parsers.base import (
    CSHARP,
    ParsedFile,
    _backend,
    _first_known_rooted,
    _GrammarUnavailable,
    _posix_rel,
    _register_resolver,
    _Resolver,
)

logger = logging.getLogger(__name__)

_NAME_TYPES = frozenset({"identifier", "qualified_name"})


@dataclass(slots=True)
class _CsImport:
    """One extracted C# ``using`` carrier.

    Not frozen: ``resolve`` flips ``is_relative`` to False on a multi-file
    namespace drop so the dispatcher marks the language known-partial.
    """

    fqn: str
    kind: str  # "import" | "static"
    is_relative: bool = True


def _dotted(node) -> str:
    if node is None or node.type not in _NAME_TYPES:
        return ""
    return node.text.decode("utf-8")


def _source_roots(known: set[str]) -> tuple[str, ...]:
    """Grammar-free ``src/`` prefixes under which namespace paths live."""
    roots: set[str] = {""}
    for path in known:
        if not path.endswith(".cs"):
            continue
        parts = _posix_rel(path).split("/")[:-1]
        if "src" in parts:
            idx = parts.index("src")
            roots.add("/".join(parts[: idx + 1]) + "/")
    return tuple(sorted(roots, key=len))


def _extract_usings(tree) -> list[_CsImport]:
    """Top-level and file-scoped ``using_directive`` nodes only."""
    out: list[_CsImport] = []
    for node in tree.root_node.children:
        if node.type == "using_directive":
            extracted = _one_using(node)
            if extracted is not None:
                out.append(extracted)
            continue
        if node.type == "file_scoped_namespace_declaration":
            for child in node.children:
                if child.type == "using_directive":
                    extracted = _one_using(child)
                    if extracted is not None:
                        out.append(extracted)
    return out


def _one_using(node) -> _CsImport | None:
    is_static = any(c.type == "static" for c in node.children)
    names = [c for c in node.children if c.type in _NAME_TYPES]
    if not names:
        return None
    # Alias form ``using X = Ns.Type;`` puts the target last; a plain or
    # static using has a single name. Either way the FQN is names[-1].
    fqn = _dotted(names[-1])
    if not fqn:
        return None
    return _CsImport(fqn=fqn, kind="static" if is_static else "import")


def _dir_cs_files(ns_path: str, known: set[str], roots: tuple[str, ...]) -> list[str]:
    """Scanned ``.cs`` files whose parent directory is ``root + ns_path``."""
    hits: list[str] = []
    seen: set[str] = set()
    for root in roots:
        parent = (root + ns_path).rstrip("/")
        for path in known:
            if not path.endswith(".cs"):
                continue
            dirname, sep, _name = path.rpartition("/")
            if not sep:
                continue
            if dirname == parent and path not in seen:
                seen.add(path)
                hits.append(path)
    return hits


def _parse_with(code: bytes, path: Path):
    return _backend.parse_source(code, CSHARP, path.suffix)


def _parse_file_csharp(code: bytes, path: Path) -> ParsedFile:
    try:
        tree = _parse_with(code, path)
    except _GrammarUnavailable:
        raise
    except Exception as e:
        logger.warning("Tree-sitter parse failed for %s: %s", path, e)
        return ParsedFile()
    imports = [
        ImportEdge(
            from_path="",
            to_path="/".join(imp.fqn.split(".")) + ".cs",
            kind=imp.kind,
        )
        for imp in _extract_usings(tree)
    ]
    return ParsedFile(imports=imports)


def _imports_from_source(code: bytes, path: Path) -> list[_CsImport]:
    try:
        tree = _parse_with(code, path)
    except _GrammarUnavailable:
        raise
    except Exception as e:
        logger.warning("Tree-sitter parse failed for %s: %s", path, e)
        return []
    return _extract_usings(tree)


def _resolve_import(
    imp: _CsImport,
    from_path: str,
    known: set[str],
    roots: tuple[str, ...] = ("",),
) -> list[str]:
    """Map one using-FQN onto an existing scanned file, or ``[]``. Never raises."""
    parts = [p for p in imp.fqn.split(".") if p]
    if not parts:
        return []
    rel_file = "/".join(parts) + ".cs"
    candidates = [rel_file]
    if len(parts) >= 2:
        candidates.append("/".join(parts[:-1]) + ".cs")
    hit = _first_known_rooted(tuple(candidates), known, roots)
    if hit:
        return [hit]
    ns_path = "/".join(parts)
    dir_hits = _dir_cs_files(ns_path, known, roots)
    if len(dir_hits) == 1:
        return dir_hits
    if len(dir_hits) >= 2:
        imp.is_relative = False  # policy drop — dispatcher marks partial
        return []
    return []


def _edge_kind(imp: _CsImport) -> str:
    return imp.kind


_register_resolver(
    CSHARP,
    _Resolver(
        parse_file=_parse_file_csharp,
        imports_from_source=_imports_from_source,
        source_roots=_source_roots,
        resolve=_resolve_import,
        edge_kind=_edge_kind,
    ),
)
