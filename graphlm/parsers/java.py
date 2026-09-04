"""Java Tree-sitter resolver (the ``graphlm[java]`` pack).

FQN → file, the Python analog: ``import com.acme.User;`` resolves to
``<root>/com/acme/User.java`` against files that exist in the scan. Source
roots are Maven/Gradle conventional prefixes (``src/main/java``,
``src/test/java``, plus a bare ``src/``), with the file's ``package``
declaration as a disambiguator. Stdlib/third-party FQNs that miss the scan
are dropped (same rule as Python).

**Wildcards are dropped.** ``import com.acme.util.*;`` would otherwise fan
out to every ``.java`` in that package, so adding one file mutates the edge
set of every wildcard importer — noisy GRAPH_DIFF for a structurally-correct
change. A dropped wildcard marks the language known-partial. Static star
imports (``import static Type.*;``) still resolve to ``Type.java``: the class
is known, it is not a package fan-out.

``kind`` is ``import`` for a type import and ``static`` for
``import static``. The grammar wheel is not imported here; a missing extra
raises ``_GrammarUnavailable``, re-raised so the dispatcher logs once.

``source_roots`` is grammar-free (path-shape only) so a missing extra cannot
escape into ``generate_graph``'s ``except Exception → deterministic_edges=None``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from graphlm.models import ImportEdge
from graphlm.parsers.base import (
    JAVA,
    ParsedFile,
    _backend,
    _first_known_rooted,
    _GrammarUnavailable,
    _posix_rel,
    _register_resolver,
    _Resolver,
)

logger = logging.getLogger(__name__)

# Longest-first conventional prefixes. A path containing src/main/java is a
# Maven root; a bare src/ (not src/main or src/test) is the simple-layout root.
_MAVEN_SUFFIXES = ("src/main/java", "src/test/java")


@dataclass(frozen=True, slots=True)
class _JavaImport:
    """One extracted Java import carrier.

    ``is_relative`` is False only for *package* wildcards (policy drop).
    Static star-imports keep True — they resolve to the class file.
    """

    fqn: str
    kind: str  # "import" | "static"
    is_relative: bool
    file_root: str  # this file's package-confirmed root, or ""


def _ident_text(node) -> str:
    """Dotted name from a package/import node's identifier child."""
    for child in node.children:
        if child.type in ("scoped_identifier", "identifier"):
            return child.text.decode("utf-8")
    return ""


def _root_from_package(path: str, package: str) -> str:
    """Source-root prefix implied by ``package`` + file path, or ``""``.

    ``src/main/java/com/acme/Foo.java`` declaring ``package com.acme`` yields
    ``src/main/java/``. A mismatch (file not where the package says) yields
    ``""`` so we do not invent a false root (#19).
    """
    posix = _posix_rel(path)
    name = posix.rsplit("/", 1)[-1]
    pkg_path = package.replace(".", "/") if package else ""
    expected = f"{pkg_path}/{name}" if pkg_path else name
    if posix == expected:
        return ""
    suffix = "/" + expected
    if posix.endswith(suffix):
        return posix[: -len(expected)]
    return ""


def _source_roots(known: set[str]) -> tuple[str, ...]:
    """Grammar-free Maven/simple-layout prefixes under which packages live."""
    roots: set[str] = {""}
    for path in known:
        if not path.endswith(".java"):
            continue
        parts = _posix_rel(path).split("/")[:-1]
        matched = False
        for i in range(len(parts), 0, -1):
            prefix = "/".join(parts[:i])
            if any(prefix == s or prefix.endswith("/" + s) for s in _MAVEN_SUFFIXES):
                roots.add(prefix + "/")
                matched = True
                break
        if matched:
            continue
        if "src" in parts:
            idx = parts.index("src")
            rest = parts[idx + 1 :]
            if rest[:1] not in ("main", "test"):
                roots.add("/".join(parts[: idx + 1]) + "/")
    return tuple(sorted(roots, key=len))


def _class_paths(fqn: str) -> tuple[str, ...]:
    """``com.acme.User`` → ``com/acme/User.java``; nested type fallback."""
    parts = [p for p in fqn.split(".") if p]
    if not parts:
        return ()
    paths = ["/".join(parts) + ".java"]
    # import com.acme.Foo.Bar (nested) → also try Foo.java.
    if (
        len(parts) >= 2
        and parts[-1][:1].isupper()
        and parts[-2][:1].isupper()
    ):
        paths.append("/".join(parts[:-1]) + ".java")
    return tuple(paths)


def _extract_imports(tree, path: Path) -> list[_JavaImport]:
    """Top-level package + import_declaration nodes only (no full-tree walk)."""
    package = ""
    raw: list[tuple[str, str, bool]] = []  # fqn, kind, package_wildcard
    for node in tree.root_node.children:
        if node.type == "package_declaration":
            package = _ident_text(node)
            continue
        if node.type != "import_declaration":
            continue
        is_static = any(c.type == "static" for c in node.children)
        wildcard = any(c.type == "asterisk" for c in node.children)
        fqn = _ident_text(node)
        if not fqn:
            continue
        if is_static and not wildcard:
            # import static com.acme.Helpers.now → class com.acme.Helpers
            head, sep, _tail = fqn.rpartition(".")
            if sep:
                fqn = head
        kind = "static" if is_static else "import"
        package_wildcard = wildcard and not is_static
        raw.append((fqn, kind, package_wildcard))
    file_root = _root_from_package(str(path), package)
    return [
        _JavaImport(
            fqn=fqn,
            kind=kind,
            is_relative=not package_wildcard,
            file_root=file_root,
        )
        for fqn, kind, package_wildcard in raw
    ]


def _parse_with(code: bytes, path: Path):
    return _backend.parse_source(code, JAVA, path.suffix)


def _parse_file_java(code: bytes, path: Path) -> ParsedFile:
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
            to_path="/".join(imp.fqn.split(".")) + ".java",
            kind=imp.kind,
        )
        for imp in _extract_imports(tree, path)
        if imp.is_relative
    ]
    return ParsedFile(imports=imports)


def _imports_from_source(code: bytes, path: Path) -> list[_JavaImport]:
    try:
        tree = _parse_with(code, path)
    except _GrammarUnavailable:
        raise
    except Exception as e:
        logger.warning("Tree-sitter parse failed for %s: %s", path, e)
        return []
    return _extract_imports(tree, path)


def _resolve_import(
    imp: _JavaImport,
    from_path: str,
    known: set[str],
    roots: tuple[str, ...] = ("",),
) -> list[str]:
    """Map one FQN onto an existing scanned file, or ``[]``. Never raises."""
    if not imp.is_relative:
        return []  # package wildcard — policy drop
    candidates = _class_paths(imp.fqn)
    if not candidates:
        return []
    try_roots: list[str] = []
    if imp.file_root:
        try_roots.append(imp.file_root)
    for root in roots:
        if root not in try_roots:
            try_roots.append(root)
    hit = _first_known_rooted(candidates, known, tuple(try_roots))
    return [hit] if hit else []


def _edge_kind(imp: _JavaImport) -> str:
    return imp.kind


_register_resolver(
    JAVA,
    _Resolver(
        parse_file=_parse_file_java,
        imports_from_source=_imports_from_source,
        source_roots=_source_roots,
        resolve=_resolve_import,
        edge_kind=_edge_kind,
    ),
)
