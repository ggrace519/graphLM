"""Registry-driven Tree-sitter backend and language-agnostic dispatch.

This module owns the shared parsing machinery: the single ``_TreeSitterBackend``
instance, the ``ParsedFile`` / ``_ParsedImport`` data carriers, the grammar
registry (``_GRAMMARS``), the resolver registry (``_RESOLVERS``), the
group-by-language dispatch in ``build_dependency_graph`` / ``parse_file``, and
the cycle detector. Language-specific extraction/resolution lives in per-language
modules (``graphlm.parsers.python``), which register themselves through the
resolver registry (see ``_ensure_resolvers``).
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

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
class _ParsedImport:
    """Unresolved import statement extracted from a Python AST."""

    module: str
    names: tuple[str, ...]
    level: int
    kind: str


# --- Grammar registry ------------------------------------------------------


@dataclass(frozen=True)
class _GrammarSpec:
    """How to load a Tree-sitter grammar: its pip module and language accessor."""

    pip_module: str  # e.g. "tree_sitter_python"
    accessor: str  # e.g. "language"


_GRAMMARS: dict[str, _GrammarSpec] = {
    "python": _GrammarSpec("tree_sitter_python", "language"),
}


class _GrammarUnavailable(Exception):
    """A grammar's pip module is not importable (opt-in pack not installed).

    Caught by ``parse_file`` / ``build_dependency_graph``, which degrade to zero
    edges for that language rather than poisoning the whole run. NOT a subclass
    of ``ValueError`` (an unregistered language) — the two are handled
    differently by the dispatch.
    """


class _TreeSitterBackend:
    """Thin wrapper around tree-sitter parsing. Lazy-imports on first use."""

    _language_cache: dict[str, object] = {}
    _ts: object | None = None

    def _import_ts(self):
        if self._ts is None:
            import tree_sitter as ts

            self._ts = ts
        return self._ts

    def _get_language(self, language: str):
        if language in self._language_cache:
            return self._language_cache[language]

        spec = _GRAMMARS.get(language)
        if spec is None:
            raise ValueError(f"Unsupported language: {language}")
        try:
            mod = importlib.import_module(spec.pip_module)
        except ImportError:
            raise _GrammarUnavailable(language)
        ts = self._import_ts()
        lang = ts.Language(getattr(mod, spec.accessor)())
        self._language_cache[language] = lang
        return lang

    def parse_source(self, code: bytes, language: str):
        ts = self._import_ts()
        lang = self._get_language(language)
        parser = ts.Parser(lang)
        return parser.parse(code)

    def build_query(self, language: str, query_str: str):
        ts = self._import_ts()
        lang = self._get_language(language)
        return ts.Query(lang, query_str)

    def run_query(self, tree, query):
        ts = self._import_ts()
        cursor = ts.QueryCursor(query)
        return cursor.matches(tree.root_node)


_backend = _TreeSitterBackend()

# Grammars already warned about as unavailable, so the "once per language"
# degradation warning is not repeated per file. Module-level so the dedupe holds
# across every call.
_WARNED_GRAMMARS: set[str] = set()


def _warn_grammar_unavailable(language: str) -> None:
    if language not in _WARNED_GRAMMARS:
        _WARNED_GRAMMARS.add(language)
        logger.warning(
            "Tree-sitter grammar for %s is not installed; contributing zero "
            "edges for that language. Install the matching language pack to "
            "enable it.",
            language,
        )


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


def _posix_rel(path: str) -> str:
    return path.replace("\\", "/")


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


# --- Resolver registry -----------------------------------------------------
#
# Each language module registers a resolver here. A resolver is the small,
# uniform surface base.py's dispatch drives without knowing the language:
#   - parse_file(code, path)   -> ParsedFile  (for parse_file())
#   - imports_from_source(code, path) -> list of language import carriers
#   - source_roots(known)      -> tuple[str, ...]  (source-root prefixes)
#   - resolve(imp, from_path, known, roots) -> list[str]  (resolved targets)
#   - edge_kind(imp)           -> str  (the ImportEdge.kind for a carrier)


@dataclass(frozen=True)
class _Resolver:
    """The language-agnostic resolver surface base.py's dispatch calls."""

    parse_file: Callable[[bytes, Path], ParsedFile]
    imports_from_source: Callable[[bytes, Path], list]
    source_roots: Callable[[set[str]], tuple[str, ...]]
    resolve: Callable[..., list[str]]
    edge_kind: Callable[..., str]


_RESOLVERS: dict[str, _Resolver] = {}
_resolvers_loaded = False


def _register_resolver(language: str, resolver: _Resolver) -> None:
    _RESOLVERS[language] = resolver


def _ensure_resolvers() -> None:
    """Import language modules so they register their resolvers.

    Called at the top of both dispatchers. A function-local import breaks the
    base <-> python module cycle (python imports names from base at module
    scope, so base must not import python at module scope).
    """
    global _resolvers_loaded
    if _resolvers_loaded:
        return
    from graphlm.parsers import python as _python  # noqa: F401

    _resolvers_loaded = True


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
    _ensure_resolvers()

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

    resolver = _RESOLVERS.get(language)
    if resolver is None:
        # A supported language with no resolver (JS/TS today): empty ParsedFile,
        # matching the prior facade behavior — not None.
        logger.debug(
            "Parsing %s with language %s not yet fully implemented",
            path,
            language,
        )
        return ParsedFile()

    try:
        return resolver.parse_file(code, path)
    except _GrammarUnavailable as e:
        _warn_grammar_unavailable(str(e) or language)
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

    Resolves imports against files that exist in ``fragments``. Stdlib,
    third-party, and missing modules are dropped. Files whose language has no
    registered resolver (or whose grammar pack is not installed) contribute zero
    edges and never abort the run — a missing grammar degrades that one language,
    never the whole graph.

    Args:
        fragments: File fragments from a scan.
        max_files: Maximum number of files to parse as import sources.
        project_dir: Base directory for resolving relative file paths.

    Returns:
        List of ImportEdge instances (never None when called).
    """
    _ensure_resolvers()

    known_files = {_posix_rel(frag.rel_path) for frag in fragments}
    # Source-root prefixes (e.g. "src/") so imports resolve in src-layout
    # projects, where scanned files live under src/ but are imported by their
    # package name (#19). Computed once per language; "" (project root) is always
    # included.
    roots_by_language: dict[str, tuple[str, ...]] = {}
    all_edges: list[ImportEdge] = []

    for frag in fragments[:max_files]:
        rel_path = _posix_rel(frag.rel_path)
        language = detect_language(Path(rel_path))
        if language is None:
            continue
        resolver = _RESOLVERS.get(language)
        if resolver is None:
            continue
        code = _source_bytes(frag, project_dir)
        if not code or not code.strip():
            continue
        if language not in roots_by_language:
            roots_by_language[language] = resolver.source_roots(known_files)
        roots = roots_by_language[language]
        try:
            imports = resolver.imports_from_source(code, Path(rel_path))
            for imp in imports:
                for to_path in resolver.resolve(imp, rel_path, known_files, roots):
                    all_edges.append(
                        ImportEdge(
                            from_path=rel_path,
                            to_path=to_path,
                            kind=resolver.edge_kind(imp),
                        )
                    )
        except _GrammarUnavailable as e:
            _warn_grammar_unavailable(str(e) or language)
            continue

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
