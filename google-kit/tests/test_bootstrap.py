"""Tests for google-kit platform registrar wiring.

ALL tests use tmp_path — no writes to ~/.cursor, ~/.codex, or ~/.claude.json.

Parity: registrar-wiring DONE; live-platform DEFERRED(P6)
"""
from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from google_kit.bootstrap import (
    bootstrap,
    default_user_config_dir,
    default_platform_paths,
    google_kit_server_entry,
    register_all,
    unregister_all,
)
from kp_mcp_bootstrap.registrars.base import ServerEntry


FAKE_BINARY = "/usr/local/bin/google-kit"


class TestServerEntry:
    def test_entry_command_and_args(self) -> None:
        entry = google_kit_server_entry(FAKE_BINARY)
        assert entry.command == FAKE_BINARY
        assert entry.args == ["mcp"]

    def test_entry_with_env(self) -> None:
        entry = google_kit_server_entry(FAKE_BINARY, env={"GOOGLE_KIT_CONFIG_DIR": "/fixture/config"})
        assert entry.env == {"GOOGLE_KIT_CONFIG_DIR": "/fixture/config"}

    def test_entry_no_secrets(self) -> None:
        entry = google_kit_server_entry(FAKE_BINARY, env={"GOOGLE_KIT_CONFIG_DIR": "/fixture/config"})
        for key in entry.env:
            assert "token" not in key.lower()
            assert "secret" not in key.lower()
            assert "password" not in key.lower()
            assert "credential" not in key.lower()


def test_bootstrap_refuses_before_profile_repair(tmp_path, monkeypatch):
    from kp_mcp_bootstrap.registrars import RegistrarError, ReasonCode

    monkeypatch.setattr("google_kit.bootstrap.default_platform_paths", lambda: {
        host: tmp_path / host / "config" for host in ("cursor", "codex", "claude")
    })
    def forbidden(**kwargs):
        pytest.fail("registration must not repair profiles")
    monkeypatch.setattr("google_kit.core.profiles.doctor_profiles", forbidden)
    for dry_run in (False, True):
        with pytest.raises(RegistrarError) as caught:
            bootstrap(binary_path=FAKE_BINARY, dry_run=dry_run,
                      env={"GOOGLE_KIT_CONFIG_DIR": str(tmp_path / "profiles")})
        assert caught.value.code is ReasonCode.CONTEXT_REQUIRED
    assert not list(tmp_path.iterdir())


class TestDefaultPlatformPaths:
    def test_paths_are_absolute(self) -> None:
        paths = default_platform_paths()
        for name, path in paths.items():
            assert path.is_absolute(), f"{name} path is not absolute: {path}"

    def test_no_temp_paths(self) -> None:
        paths = default_platform_paths()
        home = Path.home()
        for name, path in paths.items():
            assert str(path).startswith(str(home)), (
                f"{name} path does not start with home dir: {path}"
            )

    def test_default_user_config_dir_honors_explicit_env(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("GOOGLE_KIT_CONFIG_DIR", str(tmp_path / "cfg"))

        assert default_user_config_dir() == tmp_path / "cfg"
