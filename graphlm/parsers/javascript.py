"""JavaScript / TypeScript Tree-sitter resolver (the ``graphlm[js]`` pack).

One resolver, registered under both ``javascript`` and ``typescript``. Extraction
covers ``import`` / ``export … from``, ``require()``, dynamic ``import()``, and
TypeScript ``import x = require(…)``. Resolution is **relative specifiers
only** (``./foo``, ``../bar``) with an extension-probe + ``index.*`` barrel;
bare specifiers (``react``, ``@scope/pkg``, tsconfig aliases) are dropped —
the same rule as Python stdlib. A dropped bare specifier marks the language
known-partial so the pass-2 edge table is not presented as exhaustive.

The grammar wheels are *not* imported here. ``base._TreeSitterBackend`` loads
them lazily from ``_GRAMMARS``; a missing extra raises ``_GrammarUnavailable``,
which this module re-raises so the dispatcher logs once per language.

``source_roots`` is grammar-free (relative imports resolve from the importing
file, not a source-root prefix) so it cannot escape into
``generate_graph``'s ``except Exception → deterministic_edges=None`` path.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from graphlm.models import ImportEdge
from graphlm.parsers.base import (
    JAVASCRIPT,
    TYPESCRIPT,
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

# Extension probe for a relative specifier with no/partial extension. First
# hit in the scanned file set wins. Order follows the importer: a .js file
# prefers .js siblings (Node would load those); a .ts file prefers .ts
# (TypeScript's "import './x.js' often means x.ts" convention, and a
# TS-first list from a JS file would otherwise pick b.ts over b.js).
# .mts/.cts are out of scope for v1 (not in EXT_TO_LANGUAGE either).
_JS_PROBE_EXTS = (".js", ".jsx", ".mjs", ".cjs")
_TS_PROBE_EXTS = (".ts", ".tsx")
_JS_SUFFIXES = frozenset({".js", ".jsx", ".mjs", ".cjs"})


@dataclass(frozen=True, slots=True)
class _JsImport:
    """One extracted JS/TS import carrier.

    ``is_relative`` is True iff the specifier starts with ``.`` (``./`` or
    ``../``). Bare/aliased specifiers are False: the dispatcher uses that to
    trip the non-exhaustive edge-table framing when any are dropped.
    """

    specifier: str
    kind: str  # "import" | "require"
    is_relative: bool


def _js_import(specifier: str, kind: str) -> _JsImport:
    spec = specifier.replace("\\", "/").strip()
    return _JsImport(
        specifier=spec,
        kind=kind,
        is_relative=spec.startswith("."),
    )


def _string_value(node) -> str | None:
    """Unquoted contents of a ``string`` / substitution-free ``template_string``.

    Returns None for missing nodes, non-string types, empty quotes, or a
    template literal with ``${…}`` (not statically resolvable).
    """
    if node is None:
        return None
    ntype = node.type
    if ntype == "template_string":
        if any(c.type == "template_substitution" for c in node.children):
            return None
        raw = node.text.decode("utf-8")
        if len(raw) >= 2 and raw[0] == "`" and raw[-1] == "`":
            raw = raw[1:-1]
        return raw or None
    if ntype != "string":
        return None
    raw = node.text.decode("utf-8")
    if len(raw) >= 2 and raw[0] in "'\"" and raw[-1] == raw[0]:
        raw = raw[1:-1]
    return raw or None


def _source_specifier(node) -> str | None:
    """Module specifier from an import/export statement's ``source`` field.

    TypeScript ``import x = require("mod")`` stores the string on the
    ``import_require_clause`` child, not on the statement itself.
    """
    src = node.child_by_field_name("source")
    if src is None:
        for child in node.children:
            if child.type == "import_require_clause":
                src = child.child_by_field_name("source")
                break
    return _string_value(src)


def _call_import(node) -> _JsImport | None:
    """``require("mod")`` or ``import("mod")`` — string argument only."""
    fn = node.child_by_field_name("function")
    args = node.child_by_field_name("arguments")
    if fn is None or args is None:
        return None
    if fn.type == "identifier" and fn.text == b"require":
        kind = "require"
    elif fn.type == "import":
        kind = "import"
    else:
        return None
    for child in args.children:
        if child.type in ("string", "template_string"):
            spec = _string_value(child)
            return _js_import(spec, kind) if spec else None
    return None


def _extract_imports(tree) -> list[_JsImport]:
    """Walk the tree for import/export-from/require/dynamic-import specifiers.

    Walks via ``.children`` and byte-backed ``.text`` only — never
    ``start_point``/``end_point`` (py-tree-sitter 0.26.0 heap corruption on a
    full-tree point walk; see ``parsers/python.py`` skeleton).
    """
    found: list[_JsImport] = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        ntype = node.type
        if ntype == "import_statement":
            spec = _source_specifier(node)
            if spec is not None:
                kind = (
                    "require"
                    if any(c.type == "import_require_clause" for c in node.children)
                    else "import"
                )
                found.append(_js_import(spec, kind))
            continue  # source already taken; don't double-count inner strings
        if ntype == "export_statement":
            spec = _source_specifier(node)
            if spec is not None:
                found.append(_js_import(spec, "import"))
            # A local `export function` may contain require()/import() in its
            # body — keep walking. A re-export's children are not calls.
        elif ntype == "call_expression":
            captured = _call_import(node)
            if captured is not None:
                found.append(captured)
        stack.extend(reversed(node.children))
    return found


def _parse_with(code: bytes, path: Path):
    language = detect_language(path) or JAVASCRIPT
    return _backend.parse_source(code, language, path.suffix)


def _parse_file_js(code: bytes, path: Path) -> ParsedFile:
    try:
        tree = _parse_with(code, path)
    except _GrammarUnavailable:
        raise
    except Exception as e:
        logger.warning("Tree-sitter parse failed for %s: %s", path, e)
        return ParsedFile()
    imports = [
        ImportEdge(from_path="", to_path=imp.specifier, kind=imp.kind)
        for imp in _extract_imports(tree)
    ]
    return ParsedFile(imports=imports)


def _imports_from_source(code: bytes, path: Path) -> list[_JsImport]:
    try:
        tree = _parse_with(code, path)
    except _GrammarUnavailable:
        raise
    except Exception as e:
        logger.warning("Tree-sitter parse failed for %s: %s", path, e)
        return []
    return _extract_imports(tree)


def _source_roots(known: set[str]) -> tuple[str, ...]:
    """JS/TS has no Python-style source-root prefix.

    Relative specifiers resolve from the importing file. Kept grammar-free so
    a missing ``[js]`` extra cannot escape ``build_dependency_graph`` (Phase 1
    handoff item 3).
    """
    return ("",)


def _normalize_relative(from_path: str, spec: str) -> str | None:
    """Join a relative specifier onto the importing file's directory.

    Returns a posix path with ``.``/``..`` collapsed, or None if the specifier
    is not relative or walks out of the project (leading ``..`` after collapse).
    """
    spec = spec.replace("\\", "/").strip()
    if not spec.startswith("."):
        return None
    from_path = _posix_rel(from_path)
    from_dir = from_path.rsplit("/", 1)[0] if "/" in from_path else ""
    combined = f"{from_dir}/{spec}" if from_dir else spec
    parts: list[str] = []
    for part in combined.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def _probe_exts(from_path: str) -> tuple[str, ...]:
    suffix = Path(from_path).suffix.lower()
    if suffix in _JS_SUFFIXES:
        return _JS_PROBE_EXTS + _TS_PROBE_EXTS
    return _TS_PROBE_EXTS + _JS_PROBE_EXTS


def _candidates(normalized: str, from_path: str = "") -> tuple[str, ...]:
    """``<spec>``, then ``<spec>.{ext}``, then ``<spec>/index.{ext}``."""
    exts = _probe_exts(from_path)
    out: list[str] = [normalized]
    out.extend(normalized + ext for ext in exts)
    out.extend(f"{normalized}/index{ext}" for ext in exts)
    seen: set[str] = set()
    uniq: list[str] = []
    for candidate in out:
        if candidate not in seen:
            seen.add(candidate)
            uniq.append(candidate)
    return tuple(uniq)


def _resolve_import(
    imp: _JsImport,
    from_path: str,
    known: set[str],
    roots: tuple[str, ...] = ("",),
) -> list[str]:
    """Map one specifier onto an existing scanned file, or ``[]``.

    ``roots`` is part of the resolver contract (Python src-layout) and is
    ignored: JS/TS relative paths are file-relative, not source-root-relative.
    Never raises — a missing edge is preferred to a false one (#19).
    """
    del roots  # file-relative; see docstring
    normalized = _normalize_relative(from_path, imp.specifier)
    if not normalized:
        return []
    hit = _first_known(_candidates(normalized, from_path), known)
    return [hit] if hit else []


def _edge_kind(imp: _JsImport) -> str:
    return imp.kind


_js_resolver = _Resolver(
    parse_file=_parse_file_js,
    imports_from_source=_imports_from_source,
    source_roots=_source_roots,
    resolve=_resolve_import,
    edge_kind=_edge_kind,
)
_register_resolver(JAVASCRIPT, _js_resolver)
_register_resolver(TYPESCRIPT, _js_resolver)
