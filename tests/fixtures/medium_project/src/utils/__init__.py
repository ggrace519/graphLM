"""Utility functions."""

import re


def sanitize(text: str) -> str:
    """Remove control characters and trim whitespace."""
    return re.sub(r"[\x00-\x1f\x7f]", "", text).strip()


def format_output(results: list[str]) -> str:
    """Join results with newlines."""
    return "\n".join(results)


def chunk_list(items: list, size: int) -> list[list]:
    """Split a list into chunks of given size."""
    return [items[i : i + size] for i in range(0, len(items), size)]
