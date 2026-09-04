"""Go Tree-sitter resolver (the ``graphlm[go]`` pack).

``import "fmt"`` is stdlib and dropped. ``import "example.com/mod/pkg"``
resolves to a package *directory*; fanning out to every ``.go`` in that
directory would churn GRAPH_DIFF when a file is added (ADR-005/007). v1
resolves only when **exactly one** non-test ``.go`` lives in the directory
(trying the full import path, then successive suffixes so a module prefix
is optional). ``import "./rel"`` is path-relative to the importer.
A multi-file package is a policy drop and marks known-partial.

``kind`` is ``import``. ``source_roots`` is grammar-free (``("",)``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from graphlm.models import ImportEdge
from graphlm.parsers.base import (
    GO,
    ParsedFile,
    _backend,
    _GrammarUnavailable,
    _posix_rel,
    _register_resolver,
    _Resolver,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _GoImport:
    specifier: str
    is_relative: bool = True  # flipped False on multi-file package drop


def _lit(node) -> str:
    if node is None:
        return ""
    if node.type == "interpreted_string_literal_content":
        return node.text.decode("utf-8")
    if node.type == "interpreted_string_literal":
        for child in node.children:
            if child.type == "interpreted_string_literal_content":
                return child.text.decode("utf-8")
        raw = node.text.decode("utf-8")
        if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
            return raw[1:-1]
    return ""


def _import_path(spec_node) -> str:
    for child in spec_node.children:
        if child.type == "interpreted_string_literal":
            return _lit(child)
    return ""


def _extract_imports(tree) -> list[_GoImport]:
    out: list[_GoImport] = []
    for node in tree.root_node.children:
        if node.type != "import_declaration":
            continue
        for child in node.children:
            if child.type == "import_spec":
                path = _import_path(child)
                if path:
                    out.append(_GoImport(specifier=path))
            elif child.type == "import_spec_list":
                for spec in child.children:
                    if spec.type == "import_spec":
                        path = _import_path(spec)
                        if path:
                            out.append(_GoImport(specifier=path))
    return out


def _source_roots(known: set[str]) -> tuple[str, ...]:
    return ("",)


def _parse_with(code: bytes, path: Path):
    return _backend.parse_source(code, GO, path.suffix)


def _parse_file_go(code: bytes, path: Path) -> ParsedFile:
    try:
        tree = _parse_with(code, path)
    except _GrammarUnavailable:
        raise
    except Exception as e:
        logger.warning("Tree-sitter parse failed for %s: %s", path, e)
        return ParsedFile()
    imports = [
        ImportEdge(from_path="", to_path=imp.specifier, kind="import")
        for imp in _extract_imports(tree)
    ]
    return ParsedFile(imports=imports)


def _imports_from_source(code: bytes, path: Path) -> list[_GoImport]:
    try:
        tree = _parse_with(code, path)
    except _GrammarUnavailable:
        raise
    except Exception as e:
        logger.warning("Tree-sitter parse failed for %s: %s", path, e)
        return []
    return _extract_imports(tree)


def _norm_rel(path: str) -> str | None:
    parts: list[str] = []
    for p in path.replace("\\", "/").split("/"):
        if p in ("", "."):
            continue
        if p == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(p)
    return "/".join(parts)


def _pkg_go_files(dir_path: str, known: set[str]) -> list[str]:
    """Non-test ``.go`` files whose parent directory is ``dir_path``."""
    parent = dir_path.rstrip("/")
    hits: list[str] = []
    for path in known:
        if not path.endswith(".go") or path.endswith("_test.go"):
            continue
        dirname, sep, _name = path.rpartition("/")
        if not sep:
            if parent == "":
                hits.append(path)
            continue
        if dirname == parent:
            hits.append(path)
    return hits


def _dir_candidates(spec: str) -> tuple[str, ...]:
    """Full import path, then suffixes (module prefix optional)."""
    parts = [p for p in spec.split("/") if p and p != "."]
    if not parts:
        return ()
    return tuple("/".join(parts[i:]) for i in range(len(parts)))


def _resolve_import(
    imp: _GoImport,
    from_path: str,
    known: set[str],
    roots: tuple[str, ...] = ("",),
) -> list[str]:
    spec = imp.specifier.replace("\\", "/").strip()
    if not spec:
        return []
    if spec.startswith("."):
        parent = str(Path(_posix_rel(from_path)).parent)
        joined = spec if parent in (".", "") else parent + "/" + spec
        target_dir = _norm_rel(joined)
        if target_dir is None:
            return []
        hits = _pkg_go_files(target_dir, known)
    else:
        hits = []
        for cand in _dir_candidates(spec):
            hits = _pkg_go_files(cand, known)
            if hits:
                break
    if len(hits) == 1:
        return hits
    if len(hits) >= 2:
        imp.is_relative = False
        return []
    return []


def _edge_kind(imp: _GoImport) -> str:
    return "import"


_register_resolver(
    GO,
    _Resolver(
        parse_file=_parse_file_go,
        imports_from_source=_imports_from_source,
        source_roots=_source_roots,
        resolve=_resolve_import,
        edge_kind=_edge_kind,
    ),
)
