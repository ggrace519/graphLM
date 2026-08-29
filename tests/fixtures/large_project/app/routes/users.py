"""User API routes."""

from fastapi import APIRouter, HTTPException

from app.models.user import UserCreate, UserResponse
from app.services.user_service import create_user, get_user

router = APIRouter()


@router.post("/users", response_model=UserResponse)
async def create_user_endpoint(user: UserCreate):
    """Create a new user."""
    try:
        return await create_user(user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user_endpoint(user_id: int):
    """Get a user by ID."""
    user = await get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
