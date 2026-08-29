"""Core engine module."""

from __future__ import annotations

from medtest.utils.formatter import sanitize


class Engine:
    """Main processing engine."""

    def __init__(self, data: str) -> None:
        self.data = data
        self._results: list[str] = []

    def process(self) -> list[str]:
        """Process input data and return results."""
        self._results = [sanitize(line.strip()) for line in self.data.splitlines()]
        return self._results

    def get_results(self) -> list[str]:
        """Return current results."""
        return list(self._results)
