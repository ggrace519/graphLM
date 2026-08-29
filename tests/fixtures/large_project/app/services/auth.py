"""Authentication service."""

from __future__ import annotations

import hashlib


def hash_password(password: str) -> str:
    """Hash a password using SHA-256 with salt."""
    salt = "project_salt_2024"
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a hash."""
    return hash_password(password) == hashed
