"""medtest — medium test project."""

from medtest.core.engine import Engine
from medtest.utils.formatter import format_output


def run(data: str) -> str:
    """Process data and return formatted output."""
    engine = Engine(data)
    result = engine.process()
    return format_output(result)
