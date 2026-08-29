"""Item models and schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ItemCreate(BaseModel):
    title: str
    description: str | None = None
    owner_id: int


class ItemResponse(BaseModel):
    id: int
    title: str
    description: str | None
    owner_id: int
    created_at: datetime
