"""AST-based deterministic dependency parser using Tree-sitter.

Parses source files to extract import edges, exports, function definitions,
and call sites in a fully deterministic way (no LLM needed).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from graphlm.models import ImportEdge
from graphlm.scanner import FileFragment

logger = logging.getLogger(__name__)

# Supported languages
PYTHON = "python"
JAVASCRIPT = "javascript"
TYPESCRIPT = "typescript"

SUPPORTED_LANGUAGES = {PYTHON, JAVASCRIPT, TYPESCRIPT}

# Mapping from file extension to language name
EXT_TO_LANGUAGE: dict[str, str] = {
    ".py": PYTHON,
    ".js": JAVASCRIPT,
    ".ts": TYPESCRIPT,
    ".jsx": JAVASCRIPT,
    ".tsx": TYPESCRIPT,
}

_IMPORT_NODE_TYPES = frozenset(
    {"import_statement", "import_from_statement", "future_import_statement"}
)


@dataclass(frozen=True, slots=True, eq=True)
class ParsedFile:
    """AST-derived information from a single source file."""

    imports: list[ImportEdge] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    call_sites: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _ParsedImport:
    """Unresolved import statement extracted from a Python AST."""

    module: str
    names: tuple[str, ...]
    level: int
    kind: str


class _TreeSitterBackend:
    """Thin wrapper around tree-sitter parsing. Lazy-imports on first use."""

    _language_cache: dict[str, object] = {}
    _ts: object | None = None

    def _import_ts(self):
        if self._ts is None:
            import tree_sitter as ts
            import tree_sitter_python as tspython

            self._ts = ts
            self._tspython = tspython
        return self._ts, self._tspython

    def _get_language(self, language: str):
        if language in self._language_cache:
            return self._language_cache[language]

        if language == PYTHON:
            ts, tspython = self._import_ts()
            lang = ts.Language(tspython.language())
            self._language_cache[language] = lang
            return lang

        raise ValueError(f"Unsupported language: {language}")

    def parse_source(self, code: bytes, language: str):
        ts, _ = self._import_ts()
        lang = self._get_language(language)
        parser = ts.Parser(lang)
        return parser.parse(code)

    def build_query(self, language: str, query_str: str):
        ts, _ = self._import_ts()
        lang = self._get_language(language)
        return ts.Query(lang, query_str)

    def run_query(self, tree, query):
        ts, _ = self._import_ts()
        cursor = ts.QueryCursor(query)
        return cursor.matches(tree.root_node)


_backend = _TreeSitterBackend()

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


def detect_language(path: Path) -> str | None:
    """Auto-detect language from file extension.

    Args:
        path: File path to inspect.

    Returns:
        Language name (e.g. 'python') or None if unsupported.
    """
    suffix = path.suffix.lower()
    return EXT_TO_LANGUAGE.get(suffix)


def _module_to_path(module_str: str, language: str) -> str:
    """Convert a dotted module name to a naive file path (parse_file placeholder).

    Args:
        module_str: Dotted module name (e.g. 'app.routes.users').
        language: Language name.

    Returns:
        Path string (e.g. 'app/routes/users.py').
    """
    parts = [p for p in module_str.split(".") if p]
    if not parts:
        return ""
    if language == PYTHON:
        return "/".join(parts) + ".py"
    if language in (JAVASCRIPT, TYPESCRIPT):
        return "/".join(parts)
    return ""


def _node_text(node) -> str:
    return node.text.decode("utf-8")


def _field_nodes(node, field: str) -> list:
    return list(node.children_by_field_name(field))


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


def _posix_rel(path: str) -> str:
    return path.replace("\\", "/")


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


def _first_known(candidates: tuple[str, ...], known: set[str]) -> str | None:
    for candidate in candidates:
        if candidate in known:
            return candidate
    return None


def _first_known_rooted(
    candidates: tuple[str, ...], known: set[str], roots: tuple[str, ...]
) -> str | None:
    """Like _first_known, but tries each candidate under every source root.

    Root "" (project root) is tried first via the candidate order, so a
    root-layout project keeps its existing exact-match behavior.
    """
    for candidate in candidates:
        for root in roots:
            rooted = root + candidate
            if rooted in known:
                return rooted
    return None


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


def _source_bytes(frag: FileFragment, project_dir: Path | None) -> bytes | None:
    if project_dir is not None:
        fpath = project_dir / frag.rel_path
        if fpath.is_file():
            try:
                return fpath.read_bytes()
            except (OSError, PermissionError) as e:
                logger.warning("Could not read %s: %s", fpath, e)
                return None
    if frag.content:
        return frag.content.encode("utf-8")
    return None


def parse_file(path: Path, language: str | None = None) -> ParsedFile | None:
    """Parse a single source file and extract AST-derived data.

    Args:
        path: Path to the source file.
        language: Language name (auto-detected from extension if None).

    Returns:
        ParsedFile with import edges, exports, functions, and call sites.
        Returns None for unsupported file types or parse errors.
    """
    if not path.exists() or not path.is_file():
        return None

    if language is None:
        language = detect_language(path)
        if language is None:
            return None

    if language not in SUPPORTED_LANGUAGES:
        return None

    try:
        code = path.read_bytes()
    except (OSError, PermissionError) as e:
        logger.warning("Could not read %s: %s", path, e)
        return None

    if not code.strip():
        return ParsedFile()

    try:
        if language == PYTHON:
            return _parse_file_python(code, path)
        else:
            logger.debug(
                "Parsing %s with language %s not yet fully implemented",
                path,
                language,
            )
            return ParsedFile()
    except Exception as e:
        logger.warning("AST parse failed for %s: %s", path, e)
        return None


def _dedupe_edges(edges: list[ImportEdge]) -> list[ImportEdge]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[ImportEdge] = []
    for edge in edges:
        key = (edge.from_path, edge.to_path, edge.kind)
        if key not in seen:
            seen.add(key)
            unique.append(edge)
    return unique


def build_dependency_graph(
    fragments: list[FileFragment],
    max_files: int = 200,
    project_dir: Path | None = None,
) -> list[ImportEdge]:
    """Build a deterministic dependency graph from file fragments.

    Resolves Python imports against files that exist in ``fragments``.
    Stdlib, third-party, and missing modules are dropped.

    Args:
        fragments: File fragments from a scan.
        max_files: Maximum number of files to parse as import sources.
        project_dir: Base directory for resolving relative file paths.

    Returns:
        List of ImportEdge instances.
    """
    known_files = {_posix_rel(frag.rel_path) for frag in fragments}
    # Source-root prefixes (e.g. "src/") so imports resolve in src-layout
    # projects, where scanned files live under src/ but are imported by their
    # package name (#19). Computed once; "" (project root) is always included.
    roots = _source_roots(known_files)
    all_edges: list[ImportEdge] = []

    for frag in fragments[:max_files]:
        rel_path = _posix_rel(frag.rel_path)
        if detect_language(Path(rel_path)) != PYTHON:
            continue
        code = _source_bytes(frag, project_dir)
        if not code or not code.strip():
            continue
        for imp in _imports_from_source(code, Path(rel_path)):
            for to_path in _resolve_import(imp, rel_path, known_files, roots):
                all_edges.append(
                    ImportEdge(from_path=rel_path, to_path=to_path, kind=imp.kind)
                )

    return _dedupe_edges(all_edges)


def detect_import_cycles(edges: list[ImportEdge]) -> list[list[str]]:
    """Detect import cycles from dependency edges using Tarjan's algorithm.

    Args:
        edges: List of ImportEdge instances.

    Returns:
        List of cycles, each cycle being a list of file paths.
    """
    graph: dict[str, set[str]] = {}
    for edge in edges:
        graph.setdefault(edge.from_path, set()).add(edge.to_path)

    index_counter = [0]
    stack: list[str] = []
    lowlinks: dict[str, int] = {}
    index: dict[str, int] = {}
    on_stack: dict[str, bool] = {}
    sccs: list[list[str]] = []

    def strongconnect(v: str) -> None:
        index[v] = index_counter[0]
        lowlinks[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack[v] = True

        for w in graph.get(v, set()):
            if w not in index:
                strongconnect(w)
                lowlinks[v] = min(lowlinks[v], lowlinks[w])
            elif on_stack.get(w, False):
                lowlinks[v] = min(lowlinks[v], index[w])

        if lowlinks[v] == index[v]:
            scc = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                scc.append(w)
                if w == v:
                    break
            if len(scc) > 1:
                sccs.append(sorted(scc))

    for v in sorted(graph.keys()):
        if v not in index:
            strongconnect(v)

    return sccs
