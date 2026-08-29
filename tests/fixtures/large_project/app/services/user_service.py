"""User service — business logic."""

from app.models.user import UserCreate
from app.services.auth import hash_password


async def create_user(user: UserCreate) -> dict:
    """Create a new user with hashed password."""
    hashed = hash_password(user.password)
    return {"email": user.email, "name": user.name, "password_hash": hashed}


async def get_user(user_id: int) -> dict | None:
    """Retrieve a user by ID (placeholder — would query DB)."""
    return None
