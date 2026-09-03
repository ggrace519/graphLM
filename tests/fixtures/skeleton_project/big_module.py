"""Inventory service — a deliberately oversized module for skeleton tests.

This fixture exists to be longer than the scanner's default ``max_file_chars``
(4000) so ``scan_project`` skeletonises it instead of sending its head. It
carries one of everything the skeleton renderer must handle: a future import,
plain and guarded imports, a multi-line constant, a decorated class with sync
and async methods, a nested closure, a multi-line signature with a return
annotation, a private function, a ``__main__`` block, and a secret-looking
token in a docstring so the redaction-after-skeleton order is testable.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

try:
    import ujson as fastjson
except ImportError:
    fastjson = None

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

DEFAULT_WAREHOUSE = "main"
RETRY_LIMIT = 3

STOCK_LEVELS = {
    "widget": 120,
    "gadget": 45,
    "gizmo": 0,
    "doohickey": 7,
    "thingamajig": 300,
    "whatsit": 12,
}

for _name in list(STOCK_LEVELS):
    STOCK_LEVELS[_name] = max(0, STOCK_LEVELS[_name])


@dataclass
class Item:
    """A single stock-keeping unit."""

    sku: str
    quantity: int = 0
    tags: list[str] = field(default_factory=list)

    def is_in_stock(self) -> bool:
        """True when at least one unit is available."""
        return self.quantity > 0

    def restock(self, amount: int) -> None:
        if amount <= 0:
            raise ValueError("restock amount must be positive")
        self.quantity += amount
        logger.info("restocked %s by %d", self.sku, amount)


class Inventory:
    """Holds items and answers stock questions."""

    def __init__(self, warehouse: str = DEFAULT_WAREHOUSE) -> None:
        self.warehouse = warehouse
        self._items: dict[str, Item] = {}
        self._history: list[tuple[str, int]] = []

    def add(self, item: Item) -> None:
        """Register an item, replacing any existing entry for its SKU."""
        self._items[item.sku] = item
        self._history.append((item.sku, item.quantity))

    def get(self, sku: str) -> Item | None:
        return self._items.get(sku)

    def low_stock(
        self,
        threshold: int = 10,
        *,
        include_zero: bool = True,
    ) -> list[Item]:
        """Items whose quantity is at or below ``threshold``.

        Args:
            threshold: Inclusive upper bound on quantity.
            include_zero: Whether out-of-stock items count as low stock.
        """
        result = []
        for item in self._items.values():
            if item.quantity > threshold:
                continue
            if item.quantity == 0 and not include_zero:
                continue
            result.append(item)
        return sorted(result, key=lambda i: i.quantity)

    async def sync(self, client: Any) -> int:
        """Push quantities upstream with api_key = "sk-live-0123456789abcdef0123456789abcdef".

        The token above is a fixture so tests can prove secret redaction runs
        *after* skeletonisation (a docstring's first line survives into the
        skeleton). Returns the number of items sent.
        """

        def _payload(item: Item) -> dict[str, Any]:
            return {"sku": item.sku, "qty": item.quantity, "tags": item.tags}

        sent = 0
        for item in self._items.values():
            await client.post(f"/warehouses/{self.warehouse}/items", json=_payload(item))
            sent += 1
        return sent

    @property
    def total_units(self) -> int:
        return sum(item.quantity for item in self._items.values())

    @staticmethod
    def from_json(text: str) -> "Inventory":
        data = json.loads(text)
        inv = Inventory(data.get("warehouse", DEFAULT_WAREHOUSE))
        for raw in data.get("items", []):
            inv.add(Item(raw["sku"], raw.get("quantity", 0), raw.get("tags", [])))
        return inv

    def to_json(self) -> str:
        payload = {
            "warehouse": self.warehouse,
            "items": [
                {"sku": i.sku, "quantity": i.quantity, "tags": i.tags}
                for i in self._items.values()
            ],
        }
        if fastjson is not None:
            return fastjson.dumps(payload)
        return json.dumps(payload, indent=2)


def load_inventory(path: Path) -> Inventory:
    """Read an inventory JSON file from disk."""
    text = path.read_text(encoding="utf-8")
    return Inventory.from_json(text)


def save_inventory(inventory: Inventory, path: Path) -> None:
    """Write an inventory to disk as JSON."""
    path.write_text(inventory.to_json(), encoding="utf-8")


def merge_inventories(
    primary: Inventory,
    others: Iterable[Inventory],
    *,
    prefer: str = "max",
) -> Inventory:
    """Combine several inventories into one, resolving SKU clashes by ``prefer``."""
    merged = Inventory(primary.warehouse)
    for item in list(primary._items.values()):
        merged.add(Item(item.sku, item.quantity, list(item.tags)))
    for other in others:
        for item in other._items.values():
            existing = merged.get(item.sku)
            if existing is None:
                merged.add(Item(item.sku, item.quantity, list(item.tags)))
            elif prefer == "max":
                existing.quantity = max(existing.quantity, item.quantity)
            elif prefer == "sum":
                existing.quantity += item.quantity
            else:
                existing.quantity = item.quantity
    return merged


def _audit(inventory: Inventory, expected: "Sequence[str]") -> list[str]:
    missing = [sku for sku in expected if inventory.get(sku) is None]
    for sku in missing:
        logger.warning("audit: missing sku %s", sku)
    return missing


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: load, audit, and report low stock."""
    import argparse

    parser = argparse.ArgumentParser(description="inventory tools")
    parser.add_argument("path", type=Path)
    parser.add_argument("--threshold", type=int, default=10)
    args = parser.parse_args(argv)
    inv = load_inventory(args.path)
    for item in inv.low_stock(args.threshold):
        print(f"{item.sku}: {item.quantity}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
