"""Canonical map-path normalization — one definition shared across the map layers.

Map paths are compared and keyed in several places (query lookups, fan-in,
cycle membership); they must all fold Windows separators and strip a leading
``./`` the same way, or an LLM-emitted ``./a.py`` silently fails to match a
scanned ``a.py``. Kept as a stdlib-only leaf so query/degree/etc. share it
without an import cycle.
"""

from __future__ import annotations


def norm_path(path: str) -> str:
    """Canonical map path: forward slashes, no leading ``./``."""
    p = path.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p
