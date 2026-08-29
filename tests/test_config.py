"""Tests for config.py."""

import pytest

from graphlm.config import Settings


class TestSettings:
    def test_from_env_all_set(self, monkeypatch):
        monkeypatch.setenv("GRAPHLM_BASE_URL", "http://test.local/v1")
        monkeypatch.setenv("GRAPHLM_API_KEY", "test-key")
        monkeypatch.setenv("GRAPHLM_MODEL", "test-model")
        settings = Settings.from_env()
        assert settings.base_url == "http://test.local/v1"
        assert settings.api_key == "test-key"
        assert settings.model == "test-model"

    def test_from_env_missing_base_url(self, monkeypatch):
        monkeypatch.setenv("GRAPHLM_API_KEY", "key")
        monkeypatch.setenv("GRAPHLM_MODEL", "model")
        monkeypatch.delenv("GRAPHLM_BASE_URL", raising=False)
        with pytest.raises(ValueError, match="GRAPHLM_BASE_URL"):
            Settings.from_env()

    def test_from_env_missing_api_key(self, monkeypatch):
        monkeypatch.setenv("GRAPHLM_BASE_URL", "http://x")
        monkeypatch.setenv("GRAPHLM_MODEL", "model")
        monkeypatch.delenv("GRAPHLM_API_KEY", raising=False)
        with pytest.raises(ValueError, match="GRAPHLM_API_KEY"):
            Settings.from_env()

    def test_from_env_missing_model(self, monkeypatch):
        monkeypatch.setenv("GRAPHLM_BASE_URL", "http://x")
        monkeypatch.setenv("GRAPHLM_API_KEY", "key")
        monkeypatch.delenv("GRAPHLM_MODEL", raising=False)
        with pytest.raises(ValueError, match="GRAPHLM_MODEL"):
            Settings.from_env()

    def test_from_env_defaults_to_empty_raises(self, monkeypatch):
        monkeypatch.delenv("GRAPHLM_BASE_URL", raising=False)
        monkeypatch.delenv("GRAPHLM_API_KEY", raising=False)
        monkeypatch.delenv("GRAPHLM_MODEL", raising=False)
        with pytest.raises(ValueError):
            Settings.from_env()

    def test_frozen_dataclass(self):
        s = Settings(base_url="a", api_key="b", model="c")
        with pytest.raises(Exception):
            s.base_url = "changed"  # type: ignore[assignment]

    def test_slots_dataclass(self):
        s = Settings(base_url="a", api_key="b", model="c")
        with pytest.raises(AttributeError):
            s.__dict__["extra"] = "fail"  # slots don't allow __dict__
