"""Tests for the Python signature skeleton (innovation #2).

The scanner sends an oversized file's skeleton — imports, class/def headers,
docstring first lines, short constants, bodies elided — instead of its first
``max_file_chars`` characters. These tests pin the renderer's exact output on a
fixture that exercises every construct it handles, plus the dispatcher's
never-raise contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from graphlm.parser import skeleton_for
from graphlm.parsers import base as parser_base
from graphlm.parsers.python import SKELETON_HEADER, skeleton

FIXTURE = Path(__file__).parent / "fixtures" / "skeleton_project" / "big_module.py"

# The exact skeleton of the fixture. Kept inline (not a golden file) so a
# renderer change has to be a visible, reviewed edit here.
EXPECTED = '''# [graphlm skeleton: bodies elided; 202 source lines]
"""Inventory service — a deliberately oversized module for skeleton tests."""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable
try:
    import ujson as fastjson
except ImportError:
    ...
if TYPE_CHECKING:
    from collections.abc import Sequence
logger = logging.getLogger(__name__)
DEFAULT_WAREHOUSE = "main"
RETRY_LIMIT = 3
STOCK_LEVELS = {…}  # 8 lines elided
@dataclass
class Item:
    """A single stock-keeping unit."""
    sku: str
    quantity: int = 0
    tags: list[str] = field(default_factory=list)
    def is_in_stock(self) -> bool:
        """True when at least one unit is available."""
        ...
    def restock(self, amount: int) -> None:
        ...
class Inventory:
    """Holds items and answers stock questions."""
    def __init__(self, warehouse: str = DEFAULT_WAREHOUSE) -> None:
        ...
    def add(self, item: Item) -> None:
        """Register an item, replacing any existing entry for its SKU."""
        ...
    def get(self, sku: str) -> Item | None:
        ...
    def low_stock(
        self,
        threshold: int = 10,
        *,
        include_zero: bool = True,
    ) -> list[Item]:
        """Items whose quantity is at or below ``threshold``."""
        ...
    async def sync(self, client: Any) -> int:
        """Push quantities upstream with api_key = "sk-live-0123456789abcdef0123456789abcdef"."""
        ...
    @property
    def total_units(self) -> int:
        ...
    @staticmethod
    def from_json(text: str) -> "Inventory":
        ...
    def to_json(self) -> str:
        ...
def load_inventory(path: Path) -> Inventory:
    """Read an inventory JSON file from disk."""
    ...
def save_inventory(inventory: Inventory, path: Path) -> None:
    """Write an inventory to disk as JSON."""
    ...
def merge_inventories(
    primary: Inventory,
    others: Iterable[Inventory],
    *,
    prefer: str = "max",
) -> Inventory:
    """Combine several inventories into one, resolving SKU clashes by ``prefer``."""
    ...
def _audit(inventory: Inventory, expected: "Sequence[str]") -> list[str]:
    ...
def main(argv: list[str] | None = None) -> int:
    """CLI entry point: load, audit, and report low stock."""
    ...
if __name__ == "__main__":
    ...
'''

# Every class and def (module-level and class members) in the fixture.
API_NAMES = (
    "Item", "is_in_stock", "restock", "Inventory", "__init__", "add", "get",
    "low_stock", "sync", "total_units", "from_json", "to_json",
    "load_inventory", "save_inventory", "merge_inventories", "_audit", "main",
)
# Body-only text that must not leak into the skeleton.
BODY_FRAGMENTS = (
    "return ", "await ", "raise ", "self._items[", "parser.add_argument",
    "for item in", "STOCK_LEVELS[_name]", "argparse",
    # The closure inside Inventory.sync is a body, not API.
    "_payload",
    # Elided constant members and the docstring's later lines.
    '"widget"', "The token above is a fixture",
)


class TestFixtureSkeleton:
    def test_fixture_is_oversized(self):
        # The whole point: the default max_file_chars (4000) would have cut
        # this file mid-way through the first class.
        assert len(FIXTURE.read_text()) > 4000

    def test_exact_output(self):
        assert skeleton(FIXTURE.read_bytes()) == EXPECTED

    def test_shorter_than_source(self):
        assert len(skeleton(FIXTURE.read_bytes())) < len(FIXTURE.read_bytes()) / 2

    def test_contains_every_def_and_class(self):
        out = skeleton(FIXTURE.read_bytes())
        for name in API_NAMES:
            assert f" {name}(" in out or f"class {name}" in out, name

    def test_contains_no_body_statements(self):
        out = skeleton(FIXTURE.read_bytes())
        for fragment in BODY_FRAGMENTS:
            assert fragment not in out, fragment

    def test_header_carries_real_line_count(self):
        src = FIXTURE.read_bytes()
        assert skeleton(src).splitlines()[0] == SKELETON_HEADER.format(
            n=src.count(b"\n") + 1
        )

    def test_deterministic(self):
        src = FIXTURE.read_bytes()
        assert skeleton(src) == skeleton(src)


class TestRendererEdgeCases:
    """Constructs the fixture does not cover, one per branch."""

    def _lines(self, src: str) -> list[str]:
        return skeleton(src.encode()).splitlines()[1:]

    def test_short_docstring_kept_whole(self):
        src = '"""One.\nTwo.\n"""\n'
        assert self._lines(src) == ['"""One.', "Two.", '"""']

    def test_long_docstring_reduced_to_first_content_line(self):
        src = 'r"""\n\n  Summary here.\n\n  More.\n"""\n'
        assert self._lines(src) == ['r"""Summary here."""']

    def test_one_liner_def_gets_indented_placeholder(self):
        assert self._lines("def f(x): return x\n") == ["def f(x):", "    ..."]

    def test_class_with_only_pass_gets_placeholder(self):
        assert self._lines("class E(Exception):\n    pass\n") == [
            "class E(Exception):",
            "    ...",
        ]

    def test_class_docstring_then_no_members(self):
        src = 'class E:\n    """Doc.\n\n    More.\n    """\n    x = compute()\n'
        assert self._lines(src) == ['class E:', '    """Doc."""', "    x = compute()"]

    def test_elided_call_list_and_plain_rhs(self):
        src = (
            "A = build(\n  1,\n  2,\n)\n"
            "B = [\n  1,\n  2,\n]\n"
            "C: dict = {\n  1: 2,\n  3: 4,\n}\n"
            "D = 1 + (\n  2\n  + 3\n)\n"
            "E = '''\nmulti\nline\n'''\n"
        )
        assert self._lines(src) == [
            "A = build(…)  # 4 lines elided",
            "B = […]  # 4 lines elided",
            "C: dict = {…}  # 4 lines elided",
            "D = …  # 4 lines elided",
            "E = …  # 4 lines elided",
        ]

    def test_multi_line_annotation_without_value_dropped(self):
        # An annotated declaration (no "=") spanning >2 lines has nothing to
        # elide into a placeholder; it is dropped rather than rendered broken.
        src = "X: dict[\n    str,\n    int,\n]\n"
        assert self._lines(src) == []

    def test_broken_except_clause_is_dropped(self):
        # Truncated/invalid source: tree-sitter turns the colon-less except
        # into an ERROR node (verified), which the renderer ignores — the
        # try body's import still survives and nothing raises.
        src = "try:\n    import json\nexcept ImportError\n"
        assert self._lines(src) == ["try:", "    import json"]

    def test_two_line_assignment_kept_verbatim(self):
        src = "X = foo(1,\n        2)\n"
        assert self._lines(src) == ["X = foo(1,", "        2)"]

    def test_bare_expressions_and_control_flow_dropped(self):
        src = (
            "app.run()\n"
            "for i in range(3):\n    print(i)\n"
            "with open('f') as fh:\n    data = fh.read()\n"
            "while True:\n    break\n"
            "if DEBUG:\n    x = 1\n"
            "# a comment\n"
        )
        assert self._lines(src) == []

    def test_type_checking_via_module_attribute(self):
        src = "import typing\nif typing.TYPE_CHECKING:\n    from a import B\n    x = 1\nelse:\n    B = None\n"
        assert self._lines(src) == [
            "import typing",
            "if typing.TYPE_CHECKING:",
            "    from a import B",
            "else:",
            "    ...",
        ]

    def test_try_without_imports_dropped(self):
        src = "try:\n    x = 1\nexcept Exception:\n    x = 2\nfinally:\n    y = 3\n"
        assert self._lines(src) == []

    def test_try_with_import_in_except_only(self):
        src = "try:\n    x = 1\nexcept ImportError:\n    import json\n"
        assert self._lines(src) == [
            "try:",
            "    ...",
            "except ImportError:",
            "    import json",
        ]

    def test_main_guard_with_single_quotes(self):
        src = "if __name__ == '__main__':\n    main()\n    other()\n"
        assert self._lines(src) == ["if __name__ == '__main__':", "    ..."]

    def test_nested_if_inside_class_dropped(self):
        src = "class C:\n    if X:\n        y = 1\n    def m(self): pass\n"
        assert self._lines(src) == ["class C:", "    def m(self):", "        ..."]

    def test_decorated_top_level_function(self):
        src = "@app.route('/')\n@login_required\ndef index():\n    return 1\n"
        assert self._lines(src) == [
            "@app.route('/')",
            "@login_required",
            "def index():",
            "    ...",
        ]

    def test_garbage_input_does_not_raise(self):
        # tree-sitter always yields a tree (with ERROR nodes); the renderer
        # must cope with whatever it walks and still emit the header.
        out = skeleton(b"\x00\xff def (\n  class : ::\n")
        assert out.startswith("# [graphlm skeleton:")

    def test_empty_input(self):
        assert skeleton(b"") == SKELETON_HEADER.format(n=1) + "\n"


class TestSkeletonFor:
    def test_python_path_dispatches(self):
        out = skeleton_for(FIXTURE, FIXTURE.read_bytes())
        assert out == EXPECTED

    def test_non_python_language_returns_none(self):
        # TypeScript is a recognized language with no resolver (and so no
        # skeleton renderer): the scanner keeps head-truncation for it.
        assert skeleton_for(Path("app.ts"), b"export const a = 1;\n") is None

    def test_unknown_extension_returns_none(self):
        assert skeleton_for(Path("README.md"), b"# hi\n") is None

    def test_resolver_without_skeleton_returns_none(self, monkeypatch):
        py = parser_base._RESOLVERS["python"]
        bare = parser_base._Resolver(
            parse_file=py.parse_file,
            imports_from_source=py.imports_from_source,
            source_roots=py.source_roots,
            resolve=py.resolve,
            edge_kind=py.edge_kind,
        )
        assert bare.skeleton is None  # the field defaults off for other packs
        monkeypatch.setitem(parser_base._RESOLVERS, "python", bare)
        assert skeleton_for(Path("m.py"), b"x = 1\n") is None

    def test_grammar_unavailable_returns_none_and_warns_once(self, monkeypatch, caplog):
        def _boom(code):
            raise parser_base._GrammarUnavailable("python")

        py = parser_base._RESOLVERS["python"]
        monkeypatch.setitem(
            parser_base._RESOLVERS,
            "python",
            parser_base._Resolver(
                parse_file=py.parse_file,
                imports_from_source=py.imports_from_source,
                source_roots=py.source_roots,
                resolve=py.resolve,
                edge_kind=py.edge_kind,
                skeleton=_boom,
            ),
        )
        monkeypatch.setattr(parser_base, "_WARNED_GRAMMARS", set())
        with caplog.at_level("WARNING", logger="graphlm.parsers.base"):
            assert skeleton_for(Path("m.py"), b"x = 1\n") is None
            assert skeleton_for(Path("n.py"), b"x = 1\n") is None
        assert sum("not installed" in r.message for r in caplog.records) == 1

    def test_renderer_exception_returns_none_never_raises(self, monkeypatch, caplog):
        def _boom(code):
            raise RuntimeError("renderer bug")

        py = parser_base._RESOLVERS["python"]
        monkeypatch.setitem(
            parser_base._RESOLVERS,
            "python",
            parser_base._Resolver(
                parse_file=py.parse_file,
                imports_from_source=py.imports_from_source,
                source_roots=py.source_roots,
                resolve=py.resolve,
                edge_kind=py.edge_kind,
                skeleton=_boom,
            ),
        )
        with caplog.at_level("DEBUG", logger="graphlm.parsers.base"):
            assert skeleton_for(Path("m.py"), b"x = 1\n") is None
        assert any("renderer bug" in r.message for r in caplog.records)


@pytest.mark.parametrize("shim", ["graphlm.parser", "graphlm.parsers"])
def test_skeleton_for_is_re_exported(shim):
    import importlib

    mod = importlib.import_module(shim)
    assert mod.skeleton_for is parser_base.skeleton_for
    assert "skeleton_for" in mod.__all__
