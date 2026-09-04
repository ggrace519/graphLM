"""Rust Tree-sitter resolver (the ``graphlm[rust]`` pack).

Two-step, as in the language: ``mod foo;`` maps to ``foo.rs`` / ``foo/mod.rs``
(an ``include`` edge), then ``use crate::`` / ``super::`` / ``self::`` paths
resolve against a **filesystem module tree** built from the scanned ``.rs``
files, not the raw path of the specifier. External crates (``use serde::…``,
unprefixed ``use foo``) are dropped like Python stdlib.

The module tree is derived from ``known`` paths (grammar-free): ``lib.rs`` /
``main.rs`` are crate roots; ``src/foo.rs`` is module ``foo``,
``src/foo/mod.rs`` the same, ``src/foo/bar.rs`` is ``foo::bar``. ``use`` of an
item (``use crate::foo::helper``) resolves to the longest matching module
file (``foo.rs``, not a phantom ``helper.rs``).

Under-resolves honestly: inline ``mod foo { … }`` and ``#[path]`` modules are
skipped and mark the language known-partial. ``source_roots`` is grammar-free
(``("",)``) so a missing extra cannot poison the run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from graphlm.models import ImportEdge
from graphlm.parsers.base import (
    RUST,
    ParsedFile,
    _backend,
    _first_known,
    _GrammarUnavailable,
    _posix_rel,
    _register_resolver,
    _Resolver,
)

logger = logging.getLogger(__name__)

# crate_root -> { module path tuple -> file }. Keyed by the known-file set.
_TREE_CACHE: dict[frozenset[str], dict[str, dict[tuple[str, ...], str]]] = {}


@dataclass(frozen=True, slots=True)
class _RustImport:
    """One extracted Rust ``mod`` / ``use`` carrier.

    ``is_relative`` is False for policy drops (inline modules, ``#[path]``).
    External crates are not emitted at all (same as Python stdlib).
    """

    kind: str  # "include" | "import"
    is_relative: bool
    mod_name: str  # for include
    use_path: tuple[str, ...]  # ('crate','foo','bar') for import


def _source_roots(known: set[str]) -> tuple[str, ...]:
    """Grammar-free. Crate layout is derived from ``known`` at resolve time."""
    return ("",)


def _is_crate_root_name(name: str) -> bool:
    return name in ("lib.rs", "main.rs")


def _crate_root_files(known: set[str]) -> list[str]:
    roots: list[str] = []
    for path in known:
        if not path.endswith(".rs"):
            continue
        name = path.rsplit("/", 1)[-1]
        if _is_crate_root_name(name):
            roots.append(path)
            continue
        parts = path.split("/")
        if len(parts) >= 2 and parts[-2] == "bin":
            roots.append(path)
    return roots


def _owning_crate(from_path: str, known: set[str]) -> str | None:
    """Nearest ``lib.rs`` / ``main.rs`` (lib wins in the same directory)."""
    posix = _posix_rel(from_path)
    name = posix.rsplit("/", 1)[-1]
    dir_ = posix.rsplit("/", 1)[0] if "/" in posix else ""
    if _is_crate_root_name(name) or (dir_.endswith("/bin") or dir_ == "bin"):
        return posix
    parts = dir_.split("/") if dir_ else []
    for i in range(len(parts), -1, -1):
        d = "/".join(parts[:i])
        lib = f"{d}/lib.rs" if d else "lib.rs"
        main = f"{d}/main.rs" if d else "main.rs"
        if lib in known:
            return lib
        if main in known:
            return main
    return None


def _module_path_of(file: str, crate_root: str) -> tuple[str, ...] | None:
    crate_dir = crate_root.rsplit("/", 1)[0] if "/" in crate_root else ""
    if file == crate_root:
        return ()
    prefix = crate_dir + "/" if crate_dir else ""
    if crate_dir and not file.startswith(prefix):
        return None
    if not crate_dir and "/" in file:
        return None
    rel = file[len(prefix) :]
    if rel.startswith("bin/"):
        return None
    if not rel.endswith(".rs"):
        return None
    rel = rel[:-3]
    parts = rel.split("/")
    if parts[-1] == "mod":
        parts = parts[:-1]
    return tuple(parts)


def _build_trees(
    known: set[str],
) -> dict[str, dict[tuple[str, ...], str]]:
    trees: dict[str, dict[tuple[str, ...], str]] = {}
    for crate in _crate_root_files(known):
        mapping: dict[tuple[str, ...], str] = {(): crate}
        for path in sorted(p for p in known if p.endswith(".rs")):
            if path == crate:
                continue
            mp = _module_path_of(path, crate)
            if mp is None or mp == ():
                continue
            mapping.setdefault(mp, path)
        trees[crate] = mapping
    return trees


def _trees(known: set[str]) -> dict[str, dict[tuple[str, ...], str]]:
    key = frozenset(known)
    cached = _TREE_CACHE.get(key)
    if cached is None:
        cached = _build_trees(known)
        _TREE_CACHE[key] = cached
    return cached


def _ident_chain(node) -> tuple[str, ...]:
    ntype = node.type
    if ntype == "crate":
        return ("crate",)
    if ntype == "super":
        return ("super",)
    if ntype == "self":
        return ("self",)
    if ntype == "identifier":
        return (node.text.decode("utf-8"),)
    if ntype == "scoped_identifier":
        parts: list[str] = []
        for child in node.children:
            if child.type == "::":
                continue
            parts.extend(_ident_chain(child))
        return tuple(parts)
    return ()


def _expand_use(node, prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    """Flatten a use-tree node into one or more crate/super/self/ident paths."""
    ntype = node.type
    if ntype == "use_as_clause":
        return _expand_use(node.children[0], prefix) if node.children else []
    if ntype == "use_wildcard":
        paths: list[tuple[str, ...]] = []
        for child in node.children:
            if child.type == "*":
                continue
            paths.extend(_expand_use(child, prefix))
        return paths or ([prefix] if prefix else [])
    if ntype == "use_list":
        out: list[tuple[str, ...]] = []
        for child in node.children:
            if child.type in ("{", "}", ","):
                continue
            out.extend(_expand_use(child, prefix))
        return out
    if ntype == "scoped_use_list":
        new_prefix = prefix
        nested: list[tuple[str, ...]] = []
        for child in node.children:
            if child.type == "::":
                continue
            if child.type == "use_list":
                nested.extend(_expand_use(child, new_prefix))
            else:
                new_prefix = prefix + _ident_chain(child)
        return nested
    if ntype == "self":
        return [prefix] if prefix else [("self",)]
    if ntype in ("scoped_identifier", "identifier", "crate", "super"):
        return [prefix + _ident_chain(node)]
    return []


def _use_arg(node):
    """The path/tree child of a ``use_declaration`` (skip vis / use / ;)."""
    for child in node.children:
        if child.type in ("use", "visibility_modifier", ";"):
            continue
        return child
    return None


def _mod_name(node) -> str:
    for child in node.children:
        if child.type == "identifier":
            return child.text.decode("utf-8")
    return ""


def _is_inline_mod(node) -> bool:
    return any(c.type == "declaration_list" for c in node.children)


def _attr_is_path(node) -> bool:
    return b"path" in node.text


def _preceding_attrs(node) -> list:
    parent = node.parent
    if parent is None:
        return []
    kids = list(parent.children)
    try:
        idx = kids.index(node)
    except ValueError:
        return []
    attrs: list = []
    i = idx - 1
    while i >= 0 and kids[i].type in (
        "attribute_item",
        "line_comment",
        "block_comment",
    ):
        if kids[i].type == "attribute_item":
            attrs.append(kids[i])
        i -= 1
    return attrs


def _extract_imports(tree) -> list[_RustImport]:
    found: list[_RustImport] = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        ntype = node.type
        if ntype == "mod_item":
            name = _mod_name(node)
            inline = _is_inline_mod(node)
            path_attr = any(_attr_is_path(a) for a in _preceding_attrs(node))
            if inline or path_attr or not name:
                found.append(
                    _RustImport(
                        kind="include",
                        is_relative=False,
                        mod_name=name,
                        use_path=(),
                    )
                )
            else:
                found.append(
                    _RustImport(
                        kind="include",
                        is_relative=True,
                        mod_name=name,
                        use_path=(),
                    )
                )
            if inline:
                continue  # don't walk the inline body
        elif ntype == "use_declaration":
            arg = _use_arg(node)
            if arg is not None:
                for path in _expand_use(arg):
                    if not path:
                        continue
                    # crate/super/self are intra-crate; anything else is extern.
                    intra = path[0] in ("crate", "super", "self")
                    if not intra:
                        continue
                    found.append(
                        _RustImport(
                            kind="import",
                            is_relative=True,
                            mod_name="",
                            use_path=path,
                        )
                    )
            continue
        stack.extend(reversed(node.children))
    return found


def _parse_with(code: bytes, path: Path):
    return _backend.parse_source(code, RUST, path.suffix)


def _parse_file_rust(code: bytes, path: Path) -> ParsedFile:
    try:
        tree = _parse_with(code, path)
    except _GrammarUnavailable:
        raise
    except Exception as e:
        logger.warning("Tree-sitter parse failed for %s: %s", path, e)
        return ParsedFile()
    imports: list[ImportEdge] = []
    for imp in _extract_imports(tree):
        if not imp.is_relative:
            continue
        if imp.kind == "include":
            to_path = f"{imp.mod_name}.rs"
        else:
            to_path = "/".join(imp.use_path) + ".rs"
        imports.append(ImportEdge(from_path="", to_path=to_path, kind=imp.kind))
    return ParsedFile(imports=imports)


def _imports_from_source(code: bytes, path: Path) -> list[_RustImport]:
    try:
        tree = _parse_with(code, path)
    except _GrammarUnavailable:
        raise
    except Exception as e:
        logger.warning("Tree-sitter parse failed for %s: %s", path, e)
        return []
    return _extract_imports(tree)


def _mod_candidates(from_path: str, name: str) -> tuple[str, ...]:
    posix = _posix_rel(from_path)
    fname = posix.rsplit("/", 1)[-1]
    dir_ = posix.rsplit("/", 1)[0] if "/" in posix else ""
    stem = fname[:-3] if fname.endswith(".rs") else fname
    if fname in ("lib.rs", "main.rs", "mod.rs"):
        base = dir_
    else:
        base = f"{dir_}/{stem}" if dir_ else stem
    if base:
        return (f"{base}/{name}.rs", f"{base}/{name}/mod.rs")
    return (f"{name}.rs", f"{name}/mod.rs")


def _resolve_use_path(
    path: tuple[str, ...],
    cur: tuple[str, ...],
    modules: dict[tuple[str, ...], str],
) -> str | None:
    segs = list(path)
    if not segs:
        return None
    if segs[0] == "crate":
        acc: list[str] = []
        segs = segs[1:]
    elif segs[0] == "super":
        acc = list(cur)
        while segs and segs[0] == "super":
            if not acc:
                return None
            acc.pop()
            segs = segs[1:]
    elif segs[0] == "self":
        acc = list(cur)
        segs = segs[1:]
    else:
        return None
    acc.extend(segs)
    key = tuple(acc)
    if key in modules:
        return modules[key]
    if key[:-1] in modules:
        return modules[key[:-1]]
    return None


def _resolve_import(
    imp: _RustImport,
    from_path: str,
    known: set[str],
    roots: tuple[str, ...] = ("",),
) -> list[str]:
    del roots
    if not imp.is_relative:
        return []
    posix = _posix_rel(from_path)
    if imp.kind == "include":
        hit = _first_known(_mod_candidates(posix, imp.mod_name), known)
        if hit is None or hit == posix:
            return []
        return [hit]
    crate = _owning_crate(posix, known)
    if crate is None:
        return []
    modules = _trees(known).get(crate) or {}
    cur = _module_path_of(posix, crate)
    if cur is None:
        return []
    hit = _resolve_use_path(imp.use_path, cur, modules)
    if hit is None or hit == posix:
        return []
    return [hit]


def _edge_kind(imp: _RustImport) -> str:
    return imp.kind


_register_resolver(
    RUST,
    _Resolver(
        parse_file=_parse_file_rust,
        imports_from_source=_imports_from_source,
        source_roots=_source_roots,
        resolve=_resolve_import,
        edge_kind=_edge_kind,
    ),
)
