"""Item API routes."""

from fastapi import APIRouter, HTTPException

from app.models.item import ItemCreate, ItemResponse
from app.services.item_service import create_item, get_item

router = APIRouter()


@router.post("/items", response_model=ItemResponse)
async def create_item_endpoint(item: ItemCreate):
    """Create a new item."""
    return await create_item(item)


@router.get("/items/{item_id}", response_model=ItemResponse)
async def get_item_endpoint(item_id: int):
    """Get an item by ID."""
    result = await get_item(item_id)
    if not result:
        raise HTTPException(status_code=404, detail="Item not found")
    return result
