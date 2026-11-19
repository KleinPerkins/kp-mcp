"""Tests for config resolution: env precedence, defaults, headless, profile."""

from pathlib import Path

import pytest

from kp_mcp_bootstrap.config import Config, load_config
from kp_mcp_bootstrap.errors import ConfigError


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all config-related env vars so tests start from a clean slate."""
    for var in ("GOOGLE_KIT_CONFIG_DIR", "CHAOS_LABS_ROOT", "GOOGLE_KIT_PROFILE",
                "GOOGLE_KIT_HEADLESS", "CHAOS_LABS_HEADLESS"):
        monkeypatch.delenv(var, raising=False)


class TestConfigDirPrecedence:
    def test_explicit_google_kit_config_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        _clean_env(monkeypatch)
        monkeypatch.setenv("GOOGLE_KIT_CONFIG_DIR", str(tmp_path))
        cfg = load_config()
        assert cfg.config_dir == tmp_path

    def test_chaos_labs_root_fallback(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        _clean_env(monkeypatch)
        monkeypatch.setenv("CHAOS_LABS_ROOT", str(tmp_path))
        cfg = load_config()
        assert cfg.config_dir == tmp_path / "data" / "google-kit"

    def test_google_kit_config_dir_wins_over_chaos_labs_root(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _clean_env(monkeypatch)
        override = tmp_path / "explicit"
        monkeypatch.setenv("GOOGLE_KIT_CONFIG_DIR", str(override))
        monkeypatch.setenv("CHAOS_LABS_ROOT", str(tmp_path))
        cfg = load_config()
        assert cfg.config_dir == override

    def test_default_is_library_application_support(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clean_env(monkeypatch)
        cfg = load_config()
        assert cfg.config_dir == Path.home() / "Library" / "Application Support" / "google-kit"

    def test_relative_google_kit_config_dir_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clean_env(monkeypatch)
        monkeypatch.setenv("GOOGLE_KIT_CONFIG_DIR", "relative/path")
        with pytest.raises(ConfigError, match="absolute"):
            load_config()


class TestProfile:
    def test_default_profile(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clean_env(monkeypatch)
        cfg = load_config()
        assert cfg.profile == "default"

    def test_custom_profile(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clean_env(monkeypatch)
        monkeypatch.setenv("GOOGLE_KIT_PROFILE", "work")
        cfg = load_config()
        assert cfg.profile == "work"

    def test_empty_profile_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clean_env(monkeypatch)
        monkeypatch.setenv("GOOGLE_KIT_PROFILE", "   ")
        with pytest.raises(ConfigError, match="GOOGLE_KIT_PROFILE"):
            load_config()


class TestHeadless:
    @pytest.mark.parametrize("value", ["1", "true", "True", "TRUE", "yes", "YES", "on", "ON"])
    def test_truthy_values(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        _clean_env(monkeypatch)
        monkeypatch.setenv("GOOGLE_KIT_HEADLESS", value)
        assert load_config().headless is True

    @pytest.mark.parametrize("value", ["0", "false", "False", "no", "off", ""])
    def test_falsy_values(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        _clean_env(monkeypatch)
        monkeypatch.setenv("GOOGLE_KIT_HEADLESS", value)
        assert load_config().headless is False

    def test_chaos_labs_headless_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clean_env(monkeypatch)
        monkeypatch.setenv("CHAOS_LABS_HEADLESS", "1")
        assert load_config().headless is True

    def test_google_kit_headless_wins_over_chaos_labs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clean_env(monkeypatch)
        monkeypatch.setenv("GOOGLE_KIT_HEADLESS", "0")
        monkeypatch.setenv("CHAOS_LABS_HEADLESS", "1")
        assert load_config().headless is False

    def test_default_headless_is_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clean_env(monkeypatch)
        assert load_config().headless is False


class TestConfigModel:
    def test_config_is_frozen(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clean_env(monkeypatch)
        cfg = load_config()
        with pytest.raises(Exception):
            cfg.profile = "mutated"

    def test_config_fields(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        _clean_env(monkeypatch)
        monkeypatch.setenv("GOOGLE_KIT_CONFIG_DIR", str(tmp_path))
        monkeypatch.setenv("GOOGLE_KIT_PROFILE", "personal")
        monkeypatch.setenv("GOOGLE_KIT_HEADLESS", "true")
        cfg = load_config()
        assert isinstance(cfg, Config)
        assert cfg.config_dir == tmp_path
        assert cfg.profile == "personal"
        assert cfg.headless is True
