"""C / C++ Tree-sitter resolver (the ``graphlm[cpp]`` extra).

Quoted ``#include "foo.h"`` resolves relative to the importing file (plus an
extension probe). Angle-bracket ``#include <stdio.h>`` is a system header and
is dropped like Python stdlib — not partial. A macro include (``#include
FOO``) is a policy drop and marks the language known-partial.

One extra, two grammars: ``.c``/``.h`` use ``tree_sitter_c``; ``.cpp``/``.cc``/
``.cxx``/``.hpp``/``.hh``/``.hxx`` use ``tree_sitter_cpp``. ``kind`` is
``include``. ``source_roots`` is grammar-free (``("",)``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from graphlm.models import ImportEdge
from graphlm.parsers.base import (
    C,
    CPP,
    ParsedFile,
    _backend,
    _first_known,
    _GrammarUnavailable,
    _posix_rel,
    _register_resolver,
    _Resolver,
    detect_language,
)

logger = logging.getLogger(__name__)

_PROBE_EXTS = (".h", ".c", ".hpp", ".cpp", ".hh", ".cc", ".hxx", ".cxx")


@dataclass(frozen=True, slots=True)
class _Include:
    specifier: str
    is_relative: bool  # False = macro / unresolvable form (policy drop)


def _string_content(node) -> str | None:
    if node is None or node.type != "string_literal":
        return None
    for child in node.children:
        if child.type == "string_content":
            text = child.text.decode("utf-8")
            return text or None
    raw = node.text.decode("utf-8")
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        raw = raw[1:-1]
    return raw or None


def _extract_includes(tree) -> list[_Include]:
    out: list[_Include] = []
    for node in tree.root_node.children:
        if node.type != "preproc_include":
            continue
        quoted = None
        macro = False
        for child in node.children:
            if child.type == "string_literal":
                quoted = _string_content(child)
            elif child.type == "system_lib_string":
                quoted = None
                macro = False
                break
            elif child.type == "identifier":
                macro = True
        if quoted:
            spec = quoted.replace("\\", "/").strip()
            if spec:
                out.append(_Include(specifier=spec, is_relative=True))
        elif macro:
            out.append(_Include(specifier="", is_relative=False))
    return out


def _norm_rel(path: str) -> str | None:
    """Join-and-normalise a project-relative path. ``None`` if it escapes."""
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


def _source_roots(known: set[str]) -> tuple[str, ...]:
    return ("",)


def _parse_with(code: bytes, path: Path):
    language = detect_language(path) or C
    return _backend.parse_source(code, language, path.suffix)


def _parse_file_cpp(code: bytes, path: Path) -> ParsedFile:
    try:
        tree = _parse_with(code, path)
    except _GrammarUnavailable:
        raise
    except Exception as e:
        logger.warning("Tree-sitter parse failed for %s: %s", path, e)
        return ParsedFile()
    imports = [
        ImportEdge(from_path="", to_path=imp.specifier, kind="include")
        for imp in _extract_includes(tree)
        if imp.is_relative
    ]
    return ParsedFile(imports=imports)


def _imports_from_source(code: bytes, path: Path) -> list[_Include]:
    try:
        tree = _parse_with(code, path)
    except _GrammarUnavailable:
        raise
    except Exception as e:
        logger.warning("Tree-sitter parse failed for %s: %s", path, e)
        return []
    return _extract_includes(tree)


def _candidates(from_path: str, spec: str) -> tuple[str, ...]:
    parent = str(Path(_posix_rel(from_path)).parent)
    if parent in (".", ""):
        joined = spec
    else:
        joined = parent + "/" + spec
    base = _norm_rel(joined)
    if base is None:
        return ()
    out: list[str] = [base]
    stem = base.rsplit(".", 1)[0] if "." in Path(base).name else base
    for ext in _PROBE_EXTS:
        cand = stem + ext
        if cand not in out:
            out.append(cand)
    return tuple(out)


def _resolve_import(
    imp: _Include,
    from_path: str,
    known: set[str],
    roots: tuple[str, ...] = ("",),
) -> list[str]:
    if not imp.is_relative or not imp.specifier:
        return []
    hit = _first_known(_candidates(from_path, imp.specifier), known)
    return [hit] if hit else []


def _edge_kind(imp: _Include) -> str:
    return "include"


_resolver = _Resolver(
    parse_file=_parse_file_cpp,
    imports_from_source=_imports_from_source,
    source_roots=_source_roots,
    resolve=_resolve_import,
    edge_kind=_edge_kind,
)
_register_resolver(C, _resolver)
_register_resolver(CPP, _resolver)
