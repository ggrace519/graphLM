"""AST-based deterministic dependency parser using Tree-sitter.

Parses source files to extract import edges, exports, function definitions,
and call sites in a fully deterministic way (no LLM needed).

The package is registry-driven: ``base`` owns the shared machinery (the single
Tree-sitter backend, the grammar/resolver registries, the group-by-language
dispatch, cycle detection) and each ``<lang>`` module registers a resolver.
Python is the core language (always registered). JS/TS register from
``javascript``; their grammar wheels are the optional ``graphlm[js]`` extra.

Importing this package eagerly loads the language modules so their resolvers are
registered and ``build_dependency_graph`` / ``parse_file`` work immediately.
"""

from __future__ import annotations

from graphlm.parsers.base import (
    EXT_TO_LANGUAGE,
    JAVASCRIPT,
    PYTHON,
    SUPPORTED_LANGUAGES,
    TYPESCRIPT,
    ParsedFile,
    build_dependency_graph,
    detect_import_cycles,
    detect_language,
    parse_file,
    skeleton_for,
)

# Import language modules for their registration side effects. Kept here so a
# plain `import graphlm.parsers` yields a fully-wired parser; base.py also lazily
# ensures this via _ensure_resolvers() at dispatch time.
from graphlm.parsers import python as _python  # noqa: F401,E402
from graphlm.parsers import javascript as _javascript  # noqa: F401,E402

__all__ = [
    "EXT_TO_LANGUAGE",
    "JAVASCRIPT",
    "PYTHON",
    "SUPPORTED_LANGUAGES",
    "TYPESCRIPT",
    "ParsedFile",
    "build_dependency_graph",
    "detect_import_cycles",
    "detect_language",
    "parse_file",
    "skeleton_for",
]
