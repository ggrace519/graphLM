"""PHP Tree-sitter resolver (the ``graphlm[php]`` pack).

Two forms:

- ``use App\\Models\\User;`` is FQN→file (``App/Models/User.php``) under
  grammar-free ``src/`` roots, like Java. ``use function`` / ``use const``
  strip the last segment (the member) and try the parent file.
- Quoted ``require`` / ``include`` / ``require_once`` / ``include_once`` of a
  string literal resolve relative to the importer. Concatenated paths
  (``__DIR__ . "/x.php"``) are a policy drop and mark known-partial.

``kind`` is ``import`` for ``use`` and ``include`` for require/include.
The grammar accessor is ``language_php`` (the wheel also ships php_only).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from graphlm.models import ImportEdge
from graphlm.parsers.base import (
    PHP,
    ParsedFile,
    _backend,
    _first_known,
    _first_known_rooted,
    _GrammarUnavailable,
    _posix_rel,
    _register_resolver,
    _Resolver,
)

logger = logging.getLogger(__name__)

_REQUIRE_TYPES = frozenset({
    "require_expression",
    "require_once_expression",
    "include_expression",
    "include_once_expression",
})


@dataclass(slots=True)
class _PhpImport:
    specifier: str  # FQN with \\ or a relative path
    kind: str  # "import" | "include"
    is_relative: bool = True


def _fqn_text(node) -> str:
    if node is None:
        return ""
    if node.type in ("qualified_name", "name", "namespace_name"):
        return node.text.decode("utf-8")
    return node.text.decode("utf-8")


def _use_fqn(clause) -> str:
    """Dotted/backslashed name from a namespace_use_clause."""
    for child in clause.children:
        if child.type == "qualified_name":
            return child.text.decode("utf-8")
        if child.type == "name":
            return child.text.decode("utf-8")
    return ""


def _string_content(node) -> str | None:
    if node is None:
        return None
    if node.type == "encapsed_string":
        for child in node.children:
            if child.type == "string_content":
                text = child.text.decode("utf-8")
                return text or None
        raw = node.text.decode("utf-8")
        if len(raw) >= 2 and raw[0] in "'\"" and raw[-1] == raw[0]:
            return raw[1:-1] or None
    if node.type == "string":
        raw = node.text.decode("utf-8")
        if len(raw) >= 2 and raw[0] in "'\"" and raw[-1] == raw[0]:
            return raw[1:-1] or None
    return None


def _extract(tree) -> list[_PhpImport]:
    out: list[_PhpImport] = []
    for node in tree.root_node.children:
        if node.type == "namespace_use_declaration":
            for child in node.children:
                if child.type == "namespace_use_clause":
                    fqn = _use_fqn(child)
                    if fqn:
                        out.append(_PhpImport(specifier=fqn, kind="import"))
            continue
        if node.type != "expression_statement":
            continue
        for child in node.children:
            if child.type not in _REQUIRE_TYPES:
                continue
            expr = None
            for gc in child.children:
                if gc.type in ("encapsed_string", "string"):
                    expr = gc
                    break
            literal = _string_content(expr)
            if literal:
                spec = literal.replace("\\", "/").strip()
                if spec:
                    out.append(_PhpImport(specifier=spec, kind="include"))
            else:
                out.append(_PhpImport(specifier="", kind="include", is_relative=False))
    return out


def _source_roots(known: set[str]) -> tuple[str, ...]:
    roots: set[str] = {""}
    for path in known:
        if not path.endswith(".php"):
            continue
        parts = _posix_rel(path).split("/")[:-1]
        if "src" in parts:
            idx = parts.index("src")
            roots.add("/".join(parts[: idx + 1]) + "/")
    return tuple(sorted(roots, key=len))


def _parse_with(code: bytes, path: Path):
    return _backend.parse_source(code, PHP, path.suffix)


def _parse_file_php(code: bytes, path: Path) -> ParsedFile:
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
            to_path=imp.specifier.replace("\\", "/") + ("" if imp.kind == "include" else ".php"),
            kind=imp.kind,
        )
        for imp in _extract(tree)
        if imp.specifier
    ]
    return ParsedFile(imports=imports)


def _imports_from_source(code: bytes, path: Path) -> list[_PhpImport]:
    try:
        tree = _parse_with(code, path)
    except _GrammarUnavailable:
        raise
    except Exception as e:
        logger.warning("Tree-sitter parse failed for %s: %s", path, e)
        return []
    return _extract(tree)


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


def _resolve_use(fqn: str, known: set[str], roots: tuple[str, ...]) -> list[str]:
    parts = [p for p in fqn.replace("\\", "/").split("/") if p]
    if not parts:
        return []
    candidates = ["/".join(parts) + ".php"]
    if len(parts) >= 2:
        candidates.append("/".join(parts[:-1]) + ".php")
    hit = _first_known_rooted(tuple(candidates), known, roots)
    return [hit] if hit else []


def _resolve_require(spec: str, from_path: str, known: set[str]) -> list[str]:
    parent = str(Path(_posix_rel(from_path)).parent)
    joined = spec if parent in (".", "") else parent + "/" + spec
    target = _norm_rel(joined)
    if target is None:
        return []
    hit = _first_known((target,), known)
    return [hit] if hit else []


def _resolve_import(
    imp: _PhpImport,
    from_path: str,
    known: set[str],
    roots: tuple[str, ...] = ("",),
) -> list[str]:
    if not imp.is_relative:
        return []
    if imp.kind == "include":
        return _resolve_require(imp.specifier, from_path, known)
    return _resolve_use(imp.specifier, known, roots)


def _edge_kind(imp: _PhpImport) -> str:
    return imp.kind


_register_resolver(
    PHP,
    _Resolver(
        parse_file=_parse_file_php,
        imports_from_source=_imports_from_source,
        source_roots=_source_roots,
        resolve=_resolve_import,
        edge_kind=_edge_kind,
    ),
)
