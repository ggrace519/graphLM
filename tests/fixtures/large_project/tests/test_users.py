"""Basic test for user routes."""

from app.models.user import UserCreate


def test_user_create_schema():
    user = UserCreate(email="test@example.com", name="Test", password="secret")
    assert user.name == "Test"
    assert user.email == "test@example.com"
