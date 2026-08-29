"""Test for auth service."""

from app.services.auth import hash_password, verify_password


def test_hash_password():
    hashed = hash_password("secret")
    assert len(hashed) == 64  # SHA-256 hex digest


def test_verify_password():
    hashed = hash_password("mypass")
    assert verify_password("mypass", hashed) is True
    assert verify_password("wrong", hashed) is False
