"""Backwards-compatible shim for the AST parser.

The parser was split into the ``graphlm.parsers`` package (Python's resolver in
``graphlm.parsers.python``, the registry-driven backend and dispatch in
``graphlm.parsers.base``). This module re-exports the public contract so existing
imports — ``from graphlm.parser import build_dependency_graph`` etc. — keep
working unchanged.

``_source_roots`` has a leading underscore, so a star-import would not re-export
it; it is re-exported explicitly here because ``tests/test_parser.py`` imports it
directly from ``graphlm.parser``.
"""

from __future__ import annotations

from graphlm.parsers import (  # noqa: F401
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
from graphlm.parsers.python import _source_roots  # noqa: F401

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
    "_source_roots",
]
