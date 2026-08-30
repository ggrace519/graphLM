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


@dataclass(frozen=True, slots=True, eq=True)
class ParsedFile:
    """AST-derived information from a single source file."""

    imports: list[ImportEdge] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    call_sites: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ParsedFile:
    """AST-derived information from a single source file."""

    imports: list[ImportEdge] = field(default_factory=list)
    exports: list[Symbol] = field(default_factory=list)
    functions: list[FunctionDef] = field(default_factory=list)
    call_sites: list[CallSite] = field(default_factory=list)


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
    """Convert a dotted module name to a file path.

    Args:
        module_str: Dotted module name (e.g. 'app.routes.users').
        language: Language name.

    Returns:
        Path string (e.g. 'app/routes/users.py').
    """
    parts = module_str.split(".")
    if language == PYTHON:
        return "/".join(parts) + ".py"
    elif language in (JAVASCRIPT, TYPESCRIPT):
        return "/".join(parts)
    return ""


def _parse_python_imports(tree, source_lines: list[str]) -> list[ImportEdge]:
    """Extract import edges from a Python AST tree.

    Uses tree-sitter to identify import statement boundaries, then
    extracts module names from source text for reliable parsing.

    Args:
        tree: Tree-sitter parse tree.
        source_lines: Split source code lines.

    Returns:
        List of ImportEdge instances.
    """
    edges: list[ImportEdge] = []

    for node in tree.root_node.children:
        if node.type not in ("import_statement", "import_from_statement"):
            continue

        line = source_lines[node.start_point.row] if node.start_point.row < len(source_lines) else ""
        stripped = line.strip()

        if node.type == "import_from_statement":
            if "import" not in stripped:
                continue
            parts = stripped.split("import", 1)
            module_str = parts[0].replace("from", "", 1).strip()
            kind = "from"
        else:
            if not stripped.startswith("import "):
                continue
            rest = stripped[len("import "):].strip()
            module_str = rest.split(",")[0].split(" as ")[0].strip()
            kind = "import"

        if module_str:
            to_path = _module_to_path(module_str, PYTHON)
            if to_path:
                edges.append(
                    ImportEdge(from_path="", to_path=to_path, kind=kind)
                )

    return edges


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
    source_str = code.decode("utf-8", errors="replace")
    source_lines = source_str.splitlines()

    try:
        tree = _backend.parse_source(code, PYTHON)
    except Exception as e:
        logger.warning("Tree-sitter parse failed for %s: %s", path, e)
        return ParsedFile()

    imports = _parse_python_imports(tree, source_lines)
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


def build_dependency_graph(
    fragments: list[FileFragment],
    max_files: int = 200,
    project_dir: Path | None = None,
) -> list[ImportEdge]:
    """Build a deterministic dependency graph from file fragments.

    Uses AST parsing on file fragments to extract import edges.

    Args:
        fragments: File fragments from a scan.
        max_files: Maximum number of files to parse.
        project_dir: Base directory for resolving relative file paths.

    Returns:
        List of ImportEdge instances.
    """
    all_edges: list[ImportEdge] = []
    parsed_files: dict[str, ParsedFile] = {}

    for frag in fragments[:max_files]:
        fpath = Path(frag.rel_path)
        if project_dir is not None:
            fpath = project_dir / frag.rel_path
        parsed = parse_file(fpath)
        if parsed is not None:
            parsed_files[frag.rel_path] = parsed

    for rel_path, parsed in parsed_files.items():
        for edge in parsed.imports:
            from_p = edge.from_path if edge.from_path else rel_path
            all_edges.append(
                ImportEdge(from_path=from_p, to_path=edge.to_path, kind=edge.kind)
            )

    seen: set[tuple[str, str, str]] = set()
    unique_edges: list[ImportEdge] = []
    for edge in all_edges:
        key = (edge.from_path, edge.to_path, edge.kind)
        if key not in seen:
            seen.add(key)
            unique_edges.append(edge)

    return unique_edges


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
