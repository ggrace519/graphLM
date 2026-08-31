"""Python-specific Tree-sitter resolver.

All Python import extraction and resolution logic moved verbatim from the former
``graphlm/parser.py`` (#19's hard-won behavior — do not "improve"). Registers a
resolver into base.py's ``_RESOLVERS`` at import time so the language-agnostic
dispatch can drive it.
"""

from __future__ import annotations

import logging
from pathlib import Path

from graphlm.models import ImportEdge
from graphlm.parsers.base import (
    PYTHON,
    ParsedFile,
    _backend,
    _field_nodes,
    _first_known_rooted,
    _module_to_path,
    _node_text,
    _ParsedImport,
    _posix_rel,
    _register_resolver,
    _Resolver,
)

logger = logging.getLogger(__name__)

_IMPORT_NODE_TYPES = frozenset(
    {"import_statement", "import_from_statement", "future_import_statement"}
)

# --- Query strings for Python AST extraction ---

_PY_FUNC_QUERY = """\
(function_definition
  (identifier) @func.name
  (parameters) @func.params)
"""

_PY_CLASS_QUERY = """\
(class_definition
  (identifier) @class.name)
"""

_PY_CALL_QUERY = """\
(call
  (identifier) @call.simple)
(call
  (attribute) @call.attr)
"""


def _symbol_from_name_node(node) -> str:
    """Module or imported name, ignoring aliases."""
    if node.type == "aliased_import":
        target = node.child_by_field_name("name")
        return _node_text(target) if target is not None else ""
    if node.type == "wildcard_import":
        return "*"
    return _node_text(node)


def _relative_spec(node) -> tuple[int, str]:
    """Return (dot-count, remaining module) from a relative_import node."""
    level = 0
    module = ""
    for child in node.children:
        if child.type == "import_prefix":
            level = len(_node_text(child))
        elif child.type == "dotted_name":
            module = _node_text(child)
    if level == 0:
        text = _node_text(node)
        level = len(text) - len(text.lstrip("."))
        module = text.lstrip(".")
    return level, module


def _parse_import_node(node) -> list[_ParsedImport]:
    if node.type == "import_statement":
        result: list[_ParsedImport] = []
        for name_node in _field_nodes(node, "name"):
            module = _symbol_from_name_node(name_node)
            if module:
                result.append(
                    _ParsedImport(module=module, names=(), level=0, kind="import")
                )
        return result

    if node.type not in ("import_from_statement", "future_import_statement"):
        return []

    level = 0
    module = ""
    if node.type == "future_import_statement":
        module = "__future__"
    else:
        mod_node = node.child_by_field_name("module_name")
        if mod_node is None:
            return []
        if mod_node.type == "relative_import":
            level, module = _relative_spec(mod_node)
        else:
            module = _node_text(mod_node)

    names = tuple(
        symbol
        for name_node in _field_nodes(node, "name")
        if (symbol := _symbol_from_name_node(name_node))
    )
    if any(child.type == "wildcard_import" for child in node.children):
        names = ("*",)
    return [_ParsedImport(module=module, names=names, level=level, kind="from")]


def _parse_python_imports(tree) -> list[_ParsedImport]:
    """Extract import statements from a Python AST tree.

    Only top-level (module-body) statements are considered.
    """
    imports: list[_ParsedImport] = []
    for node in tree.root_node.children:
        if node.type in _IMPORT_NODE_TYPES:
            imports.extend(_parse_import_node(node))
    return imports


def _placeholder_edge(imp: _ParsedImport) -> ImportEdge | None:
    """Single-file view of an import: module name as a naive .py path."""
    if not imp.module:
        return None
    to_path = _module_to_path(imp.module, PYTHON)
    if not to_path:
        return None
    return ImportEdge(from_path="", to_path=to_path, kind=imp.kind)


def _module_candidates(dotted: str) -> tuple[str, ...]:
    if not dotted:
        return ()
    rel = dotted.replace(".", "/")
    return (f"{rel}.py", f"{rel}/__init__.py")


# Directory names conventionally placed on the interpreter path (so packages
# under them are imported by bare package name). Only these are accepted as
# source roots — deriving arbitrary prefixes instead manufactured FALSE edges,
# e.g. a `tests/stub/requests/__init__.py` shadow letting third-party
# `import requests` resolve to a project-internal file, which a plain suffix or
# every-prefix search cannot avoid (#19). A false edge in the "do-not-contradict"
# ground-truth table is worse than a missing one, so the set is deliberately a
# small allowlist of real Python source-layout roots.
_SOURCE_ROOT_NAMES = ("src", "lib", "python")


def _source_roots(known: set[str]) -> tuple[str, ...]:
    """Directory prefixes under which packages live (for src-layout projects).

    A module imported as ``argus.core`` resolves to ``argus/core/__init__.py``
    relative to the *package root*, but in a src-layout project the scanned file
    is ``src/argus/core/__init__.py`` — the ``src/`` root is on the interpreter
    path, not in the import name. Without accounting for it, no intra-project
    edge resolves and the whole AST graph comes back empty (#19).

    Returns the prefixes to try before a candidate path, always including "" (the
    project root). A prefix is accepted only when its final segment is a
    conventional source-root name (``_SOURCE_ROOT_NAMES``) AND it directly
    contains a Python package (``<root>/<pkg>/__init__.py`` is in the scan). This
    is intentionally conservative — it will not invent a root from an arbitrary
    directory that merely happens to contain an ``__init__.py`` (which produced
    false edges), at the cost of missing an unconventional custom source root.
    """
    roots: set[str] = {""}
    for path in known:
        if not path.endswith("/__init__.py"):
            continue
        parts = path.split("/")
        # parts[-2] is the package dir; parts[:-2] is the prefix before it. The
        # root's LAST segment must be a conventional source-root name.
        prefix_parts = parts[:-2]
        if prefix_parts and prefix_parts[-1] in _SOURCE_ROOT_NAMES:
            roots.add("/".join(prefix_parts) + "/")
    return tuple(sorted(roots, key=len))


def _resolve_module_name(from_path: str, module: str, level: int) -> str | None:
    """Dotted module for an import, or None if a relative import escapes the tree.

    Standard Python: one leading dot is the importing file's package (parent dir).
    Each extra dot walks up one directory.
    """
    if level <= 0:
        return module
    parent_parts = _posix_rel(from_path).split("/")[:-1]
    if parent_parts == [""]:
        parent_parts = []
    up = level - 1
    if up > len(parent_parts):
        return None
    base = parent_parts[:-up] if up else parent_parts
    extra = [p for p in module.split(".") if p] if module else []
    return ".".join(base + extra)


def _resolve_import(
    imp: _ParsedImport,
    from_path: str,
    known: set[str],
    roots: tuple[str, ...] = ("",),
) -> list[str]:
    """Map one import statement onto existing project files.

    ``from a.b import name1, name2`` prefers each name as a submodule
    (``a/b/name.py`` or ``a/b/name/__init__.py``). Names that are not
    submodules fall back to the package/module itself once. ``roots`` are the
    source-root prefixes to try before each candidate (src-layout support, #19).
    """
    dotted = _resolve_module_name(from_path, imp.module, imp.level)
    if dotted is None:
        return []

    if imp.kind == "import":
        hit = _first_known_rooted(_module_candidates(dotted), known, roots)
        return [hit] if hit else []

    found: list[str] = []
    seen: set[str] = set()
    need_fallback = not imp.names
    for name in imp.names:
        if name == "*":
            need_fallback = True
            continue
        sub = f"{dotted}.{name}" if dotted else name
        hit = _first_known_rooted(_module_candidates(sub), known, roots)
        if hit is None:
            need_fallback = True
            continue
        if hit not in seen:
            seen.add(hit)
            found.append(hit)
    if need_fallback:
        hit = _first_known_rooted(_module_candidates(dotted), known, roots)
        if hit is not None and hit not in seen:
            found.append(hit)
    return found


def _parse_python_functions(tree) -> list[str]:
    """Extract function names from a Python AST tree."""
    names: list[str] = []

    query = _backend.build_query(PYTHON, _PY_FUNC_QUERY)
    matches = _backend.run_query(tree, query)
    for _pat_idx, captures in matches:
        for cap_name, nodes in captures.items():
            if "func.name" in cap_name:
                for n in nodes:
                    name = n.text.decode()
                    names.append(name)

    return list(dict.fromkeys(names))  # dedupe preserving order


def _parse_python_classes(tree) -> list[str]:
    """Extract class names from a Python AST tree."""
    names: list[str] = []
    query = _backend.build_query(PYTHON, _PY_CLASS_QUERY)
    matches = _backend.run_query(tree, query)

    for _pat_idx, captures in matches:
        for cap_name, nodes in captures.items():
            for node in nodes:
                if "class.name" in cap_name:
                    names.append(node.text.decode())

    return names


def _parse_python_calls(tree) -> list[str]:
    """Extract call site names from a Python AST tree."""
    names: list[str] = []
    query = _backend.build_query(PYTHON, _PY_CALL_QUERY)
    matches = _backend.run_query(tree, query)

    for _pat_idx, captures in matches:
        for cap_name, nodes in captures.items():
            for node in nodes:
                if "attr" in cap_name:
                    idents = [c for c in node.children if c.type == "identifier"]
                    if not idents:
                        continue
                    names.append(idents[-1].text.decode())
                else:
                    names.append(node.text.decode())

    return list(dict.fromkeys(names))  # dedupe preserving order


def _parse_file_python(code: bytes, path: Path) -> ParsedFile:
    """Parse a Python source file.

    Args:
        code: Source code as bytes.
        path: File path (for extracting module-relative imports).

    Returns:
        ParsedFile with extracted AST data.
    """
    try:
        tree = _backend.parse_source(code, PYTHON)
    except Exception as e:
        logger.warning("Tree-sitter parse failed for %s: %s", path, e)
        return ParsedFile()

    raw_imports = _parse_python_imports(tree)
    imports = [edge for imp in raw_imports if (edge := _placeholder_edge(imp)) is not None]
    functions = _parse_python_functions(tree)
    classes = _parse_python_classes(tree)
    calls = _parse_python_calls(tree)

    exports: list[str] = list(classes)
    for func in functions:
        if not func.startswith("_") or (func.startswith("__") and func.endswith("__")):
            exports.append(func)

    return ParsedFile(
        imports=imports,
        exports=exports,
        functions=functions,
        call_sites=calls,
    )


def _imports_from_source(code: bytes, path: Path) -> list[_ParsedImport]:
    try:
        tree = _backend.parse_source(code, PYTHON)
    except Exception as e:
        logger.warning("Tree-sitter parse failed for %s: %s", path, e)
        return []
    return _parse_python_imports(tree)


def _edge_kind(imp: _ParsedImport) -> str:
    return imp.kind


_register_resolver(
    PYTHON,
    _Resolver(
        parse_file=_parse_file_python,
        imports_from_source=_imports_from_source,
        source_roots=_source_roots,
        resolve=_resolve_import,
        edge_kind=_edge_kind,
    ),
)
