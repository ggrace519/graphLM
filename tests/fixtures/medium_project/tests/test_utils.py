"""Tests for utils."""

from src.utils import sanitize, format_output, chunk_list


def test_sanitize():
    assert sanitize("hello\n") == "hello"
    assert sanitize("  spaces  ") == "spaces"


def test_format_output():
    assert format_output(["a", "b"]) == "a\nb"


def test_chunk_list():
    assert chunk_list([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
