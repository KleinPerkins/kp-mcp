"""Adversarial tests for load_config edge cases.

load_config is purely environment-driven (no config file is read), so the
"malformed file" surface does not apply here; these tests pin the documented
precedence and the absolute-path guard against contrived inputs.
"""

import pytest

from kp_mcp_bootstrap.config import load_config
from kp_mcp_bootstrap.errors import ConfigError


def _clean(monkeypatch: pytest.MonkeyPatch) -> None:
    for v in ("GOOGLE_KIT_CONFIG_DIR", "CHAOS_LABS_ROOT", "GOOGLE_KIT_PROFILE",
              "GOOGLE_KIT_HEADLESS", "CHAOS_LABS_HEADLESS"):
        monkeypatch.delenv(v, raising=False)


class TestConfigDirGuards:
    def test_tilde_path_is_rejected_as_non_absolute(self, monkeypatch) -> None:
        _clean(monkeypatch)
        # ~ is NOT expanded by load_config and is not an absolute path -> fail loud.
        monkeypatch.setenv("GOOGLE_KIT_CONFIG_DIR", "~/cfg")
        with pytest.raises(ConfigError, match="absolute"):
            load_config()

    def test_empty_config_dir_falls_through_to_default(self, monkeypatch, tmp_path) -> None:
        _clean(monkeypatch)
        monkeypatch.setenv("GOOGLE_KIT_CONFIG_DIR", "")  # falsy -> ignored
        monkeypatch.setenv("CHAOS_LABS_ROOT", str(tmp_path))
        cfg = load_config()
        assert cfg.config_dir == tmp_path / "data" / "google-kit"

    def test_explicit_dir_wins_and_profile_stripped(self, monkeypatch, tmp_path) -> None:
        _clean(monkeypatch)
        monkeypatch.setenv("GOOGLE_KIT_CONFIG_DIR", str(tmp_path))
        monkeypatch.setenv("GOOGLE_KIT_PROFILE", "  work  ")
        cfg = load_config()
        assert cfg.config_dir == tmp_path
        assert cfg.profile == "work"


class TestProfileGuards:
    def test_whitespace_profile_rejected(self, monkeypatch) -> None:
        _clean(monkeypatch)
        monkeypatch.setenv("GOOGLE_KIT_PROFILE", "\t  \n")
        with pytest.raises(ConfigError, match="GOOGLE_KIT_PROFILE"):
            load_config()
