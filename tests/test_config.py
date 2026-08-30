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

    def test_timeout_defaults_to_300(self, monkeypatch):
        monkeypatch.setenv("GRAPHLM_BASE_URL", "http://x")
        monkeypatch.setenv("GRAPHLM_API_KEY", "k")
        monkeypatch.setenv("GRAPHLM_MODEL", "m")
        monkeypatch.delenv("GRAPHLM_TIMEOUT", raising=False)
        assert Settings.from_env().timeout == 300.0

    def test_timeout_from_env(self, monkeypatch):
        monkeypatch.setenv("GRAPHLM_BASE_URL", "http://x")
        monkeypatch.setenv("GRAPHLM_API_KEY", "k")
        monkeypatch.setenv("GRAPHLM_MODEL", "m")
        monkeypatch.setenv("GRAPHLM_TIMEOUT", "600")
        assert Settings.from_env().timeout == 600.0

    def test_max_output_tokens_default_matches_llm(self, monkeypatch):
        from graphlm.llm import LLM_MAX_OUTPUT_TOKENS

        monkeypatch.setenv("GRAPHLM_BASE_URL", "http://x")
        monkeypatch.setenv("GRAPHLM_API_KEY", "k")
        monkeypatch.setenv("GRAPHLM_MODEL", "m")
        monkeypatch.delenv("GRAPHLM_MAX_OUTPUT_TOKENS", raising=False)
        # The config default must equal the client's default so the reserve and
        # the requested max_tokens can never drift (#17/#18).
        assert Settings.from_env().max_output_tokens == LLM_MAX_OUTPUT_TOKENS

    def test_max_output_tokens_from_env(self, monkeypatch):
        monkeypatch.setenv("GRAPHLM_BASE_URL", "http://x")
        monkeypatch.setenv("GRAPHLM_API_KEY", "k")
        monkeypatch.setenv("GRAPHLM_MODEL", "m")
        monkeypatch.setenv("GRAPHLM_MAX_OUTPUT_TOKENS", "48000")
        assert Settings.from_env().max_output_tokens == 48000
