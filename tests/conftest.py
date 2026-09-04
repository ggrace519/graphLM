"""Shared fixtures for graphLM tests."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def small_project() -> Path:
    """Path to the small test fixture project."""
    return FIXTURES_DIR / "small_project"


@pytest.fixture(scope="session")
def medium_project() -> Path:
    """Path to the medium test fixture project."""
    return FIXTURES_DIR / "medium_project"


@pytest.fixture(scope="session")
def large_project() -> Path:
    """Path to the large test fixture project."""
    return FIXTURES_DIR / "large_project"


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """Path to the fixtures directory."""
    return FIXTURES_DIR


@pytest.fixture(scope="session")
def ts_project() -> Path:
    """Path to the TypeScript fixture project (JS/TS pack)."""
    return FIXTURES_DIR / "ts_project"


@pytest.fixture(scope="session")
def java_project() -> Path:
    """Path to the Java fixture project (Java pack)."""
    return FIXTURES_DIR / "java_project"


@pytest.fixture(scope="session")
def rust_project() -> Path:
    """Path to the Rust fixture project (Rust pack)."""
    return FIXTURES_DIR / "rust_project"


@pytest.fixture(scope="session")
def ignore_project() -> Path:
    """Path to the ``.graphlmignore`` fixture project (#38)."""
    return FIXTURES_DIR / "ignore_project"
