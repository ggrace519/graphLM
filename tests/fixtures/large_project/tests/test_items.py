"""Test for item routes."""

from app.models.item import ItemCreate


def test_item_create_schema():
    item = ItemCreate(title="Test", owner_id=1)
    assert item.title == "Test"
    assert item.description is None
