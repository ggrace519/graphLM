"""Basic test for mylib helpers."""

from mylib.helpers import add, greet


def test_add():
    assert add(1, 2) == 3
    assert add(-1, 1) == 0


def test_greet():
    assert greet("World") == "Hello, World!"
