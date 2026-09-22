"""Test-path detection — a single shared predicate for "is this a test file?".

Kept as a stdlib-only leaf module (imports nothing from ``graphlm``) so the
scanner, the renderers, the cycle labeller, and the MCP query layer can all
share one definition without creating an import cycle. The scanner uses it to
drop tests under ``--no-tests``; the map layers use it to *label* test code
(cycles whose every member is a test file) rather than hide it — so the
invariant "labelled as test ⇔ dropped by ``--no-tests``" holds by construction.
"""

from __future__ import annotations

_TEST_DIR_NAMES = {"tests", "test", "__tests__"}


def is_test_path(rel_path: str) -> bool:
    """True for test files/dirs — not names that merely contain ``test`` (#94).

    ``latest.py`` / ``contest.py`` / ``testing.py`` are ordinary modules.
    ``test_foo.py``, ``foo_test.py``, ``foo.test.js``, and anything under
    ``tests/`` / ``test/`` / ``__tests__/`` are tests.
    """
    rel = rel_path.replace("\\", "/").lower()
    parts = rel.split("/")
    name = parts[-1]
    stem = name.rsplit(".", 1)[0] if "." in name else name
    dir_parts = parts[:-1]
    if parts[0] in _TEST_DIR_NAMES or any(p in _TEST_DIR_NAMES for p in dir_parts):
        return True
    if stem.startswith("test_") or stem.endswith("_test") or stem == "test":
        return True
    if ".test." in name or ".spec." in name:
        return True
    return False
