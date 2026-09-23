"""Tests for canonical map-path normalization (``graphlm.pathnorm``)."""

from __future__ import annotations

import pytest

from graphlm.pathnorm import norm_path


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("a.py", "a.py"),
        ("./a.py", "a.py"),
        ("././a.py", "a.py"),  # repeated leading ./
        ("pkg/mod.py", "pkg/mod.py"),
        (r"pkg\mod.py", "pkg/mod.py"),  # backslashes folded
        (r".\pkg\mod.py", "pkg/mod.py"),
        ("", ""),
    ],
)
def test_norm_path(raw: str, expected: str) -> None:
    assert norm_path(raw) == expected
