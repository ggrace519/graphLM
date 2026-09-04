"""Tests for config.py."""

import os

import pytest

from graphlm.config import Settings, _load_env_files, _user_config_path


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
        with pytest.raises(ValueError, match=r"GRAPHLM_BASE_URL.*~/.config/graphlm/.env"):
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


# A dedicated key the user-config file never shares with real GRAPHLM_*
# settings. load_dotenv mutates os.environ directly (monkeypatch cannot roll
# back a delenv of a var that was absent), so a probe key also keeps any
# value the loader sets from leaking into other tests.
_PROBE = "GRAPHLM_USER_CONFIG_PROBE"


class TestUserConfigPath:
    def test_honors_xdg_config_home(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        assert _user_config_path() == tmp_path / "graphlm" / ".env"

    def test_falls_back_to_home_config_when_xdg_unset(self, monkeypatch, tmp_path):
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))  # Path.home() honors $HOME on POSIX
        assert _user_config_path() == tmp_path / ".config" / "graphlm" / ".env"

    def test_empty_xdg_config_home_falls_back_to_home(self, monkeypatch, tmp_path):
        # "$XDG_CONFIG_HOME when set AND non-empty" — empty must fall back.
        monkeypatch.setenv("XDG_CONFIG_HOME", "")
        monkeypatch.setenv("HOME", str(tmp_path))
        assert _user_config_path() == tmp_path / ".config" / "graphlm" / ".env"


class TestLoadEnvFiles:
    def test_user_config_supplies_value_when_unset(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        cfgdir = tmp_path / "xdg" / "graphlm"
        cfgdir.mkdir(parents=True)
        (cfgdir / ".env").write_text(f"{_PROBE}=from-user-config\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.delenv(_PROBE, raising=False)

        _load_env_files()

        assert os.environ.get(_PROBE) == "from-user-config"

    def test_shell_env_wins_over_user_config(self, monkeypatch, tmp_path):
        # Precedence: a value already in os.environ (simulating an exported
        # shell var) must NOT be overwritten by the user config.
        monkeypatch.chdir(tmp_path)
        cfgdir = tmp_path / "xdg" / "graphlm"
        cfgdir.mkdir(parents=True)
        (cfgdir / ".env").write_text(f"{_PROBE}=from-user-config\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.setenv(_PROBE, "from-shell")  # recorded → rolled back by monkeypatch

        _load_env_files()

        assert os.environ.get(_PROBE) == "from-shell"

    def test_cwd_env_is_ignored(self, monkeypatch, tmp_path):
        # ADR-009: a .env in the working directory is not graphlm config.
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text(f"{_PROBE}=from-cwd-env\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-such-xdg"))
        monkeypatch.delenv(_PROBE, raising=False)

        _load_env_files()

        assert os.environ.get(_PROBE) is None

    def test_parent_env_is_ignored(self, monkeypatch, tmp_path):
        # find_dotenv(usecwd=True) used to walk ancestors; a parent .env
        # must stay ignored even if cwd has none of its own.
        parent = tmp_path / "repo"
        cwd = parent / "subdir"
        cwd.mkdir(parents=True)
        (parent / ".env").write_text(f"{_PROBE}=from-parent-env\n")
        monkeypatch.chdir(cwd)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-such-xdg"))
        monkeypatch.delenv(_PROBE, raising=False)

        _load_env_files()

        assert os.environ.get(_PROBE) is None

    def test_cwd_env_does_not_override_user_config(self, monkeypatch, tmp_path):
        # A scanned project's .env must not shadow ~/.config/graphlm/.env.
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text(f"{_PROBE}=from-cwd-env\n")
        cfgdir = tmp_path / "xdg" / "graphlm"
        cfgdir.mkdir(parents=True)
        (cfgdir / ".env").write_text(f"{_PROBE}=from-user-config\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.delenv(_PROBE, raising=False)

        _load_env_files()

        assert os.environ.get(_PROBE) == "from-user-config"

    def test_missing_user_config_is_clean_noop(self, monkeypatch, tmp_path):
        # Point XDG at a dir with no graphlm/.env, and a decoy .env in cwd:
        # loading must not raise and must not invent the probe var.
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text(f"{_PROBE}=from-cwd-env\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty-xdg"))
        monkeypatch.delenv(_PROBE, raising=False)

        _load_env_files()  # must not raise

        assert os.environ.get(_PROBE) is None
