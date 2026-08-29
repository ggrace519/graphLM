"""Item service — business logic."""

from app.models.item import ItemCreate


async def create_item(item: ItemCreate) -> dict:
    """Create a new item (placeholder)."""
    return {
        "title": item.title,
        "description": item.description,
        "owner_id": item.owner_id,
    }


async def get_item(item_id: int) -> dict | None:
    """Retrieve an item by ID (placeholder)."""
    return None
