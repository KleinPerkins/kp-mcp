"""Tests for snow-kit platform registrar wiring (idempotent; tmp_path only)."""
from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from snow_kit.bootstrap import (
    _assert_live_tool_success,
    doctor,
    register_all,
    server_entry,
    setup,
    status,
    status_all,
    unregister_all,
)
from snow_kit.core.config import CONFIG_PATH_ENV, ConfigError, resolve_snowflake_user


@pytest.fixture(autouse=True)
def _isolated_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CONFIG_PATH_ENV, str(tmp_path / "missing-config.env"))


def test_connector_dependency_includes_secure_local_storage_extra() -> None:
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))

    assert "snowflake-connector-python[secure-local-storage]>=3.18.0" in data["project"]["dependencies"]


def test_registration_refuses_without_context(tmp_path):
    from kp_mcp_bootstrap.registrars import RegistrarError, ReasonCode
    with pytest.raises(RegistrarError) as caught:
        register_all(cursor_path=tmp_path / "cursor", codex_path=tmp_path / "codex",
                     claude_path=tmp_path / "claude", binary_path="/opt/snow-kit")
    assert caught.value.code is ReasonCode.CONTEXT_REQUIRED
    assert not list(tmp_path.iterdir())

def test_bootstrap_includes_user_from_snowflake_user_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SNOWFLAKE_USER", "alice@example.invalid")
    monkeypatch.delenv("SNOW_KIT_USER", raising=False)

    entry = server_entry(binary_path="/bin/snow-kit", config_path=tmp_path / "config.env")
    assert entry.env == {CONFIG_PATH_ENV: str(tmp_path / "config.env")}


def test_bootstrap_prefers_snow_kit_user_over_snowflake_user(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SNOW_KIT_USER", "explicit@example.invalid")
    monkeypatch.setenv("SNOWFLAKE_USER", "legacy@example.invalid")

    entry = server_entry(binary_path="/bin/snow-kit", config_path=tmp_path / "config.env")
    assert entry.env == {CONFIG_PATH_ENV: str(tmp_path / "config.env")}


def test_bootstrap_reads_hermetic_local_profile(tmp_path, monkeypatch) -> None:
    fixture = tmp_path / "config.env"
    fixture.write_text("SNOW_KIT_USER=operator@example.invalid\n", encoding="utf-8")
    fixture.chmod(0o600)
    monkeypatch.delenv("SNOW_KIT_USER", raising=False)
    monkeypatch.delenv("SNOWFLAKE_USER", raising=False)
    monkeypatch.setenv(CONFIG_PATH_ENV, str(fixture))
    assert resolve_snowflake_user(cursor_path=tmp_path / "cursor.json") == "operator@example.invalid"


def test_rebootstrap_preserves_unowned_legacy_entry(tmp_path):
    from kp_mcp_bootstrap.registrars import RegistrarError
    cursor = tmp_path / "cursor.json"
    original = b'{"mcpServers":{"snow-kit":{"command":"/legacy","env":{"SNOW_KIT_USER":"private"}}}}'
    cursor.write_bytes(original)
    with pytest.raises(RegistrarError):
        register_all(cursor_path=cursor, codex_path=tmp_path / "codex",
                     claude_path=tmp_path / "claude", binary_path="/opt/snow-kit")
    assert cursor.read_bytes() == original

def test_resolve_snowflake_user_from_registered_mcp(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SNOW_KIT_USER", raising=False)
    monkeypatch.delenv("SNOWFLAKE_USER", raising=False)
    monkeypatch.delenv("SNOW_KIT_LEGACY_CONFIG_PATH", raising=False)

    cursor = tmp_path / "cursor.json"
    cursor.write_text(
        '{"mcpServers": {"snow-kit": {"env": {"SNOW_KIT_USER": "mcp@example.invalid"}}}}',
        encoding="utf-8",
    )

    assert resolve_snowflake_user(cursor_path=cursor) == "mcp@example.invalid"


def test_resolve_snowflake_user_does_not_guess_from_git_email(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SNOW_KIT_USER", raising=False)
    monkeypatch.delenv("SNOWFLAKE_USER", raising=False)
    monkeypatch.delenv("SNOW_KIT_LEGACY_CONFIG_PATH", raising=False)

    with patch(
        "snow_kit.core.config.subprocess.run",
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="bob@example.invalid\n"),
    ):
        assert resolve_snowflake_user(cursor_path=tmp_path / "missing-cursor.json") is None


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"SNOW_KIT_USER": "kit@example.invalid"}, "kit@example.invalid"),
        ({"SNOWFLAKE_USER": "flake@example.invalid"}, "flake@example.invalid"),
    ],
)
def test_resolve_snowflake_user_env_precedence(
    monkeypatch: pytest.MonkeyPatch,
    env: dict[str, str],
    expected: str,
) -> None:
    for key in ("SNOW_KIT_USER", "SNOWFLAKE_USER", "SNOW_KIT_LEGACY_CONFIG_PATH"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert resolve_snowflake_user() == expected


def test_status_without_context_is_unknown_and_redacted(tmp_path):
    cursor = tmp_path / "cursor.json"
    cursor.write_text('{"mcpServers":{"sibling":{"secret":"sensitive-sibling-value"}}}')
    before = cursor.read_bytes()
    result = status_all(cursor_path=cursor, codex_path=tmp_path / "codex",
                        claude_path=tmp_path / "claude", binary_path="/opt/snow-kit")
    assert all(item["present"] is None and item["canonical"] is None for item in result.values())
    assert all(item["reason_codes"] == ["context_required"] for item in result.values())
    assert "sensitive-sibling-value" not in json.dumps(result)
    assert cursor.read_bytes() == before

def test_registration_rejects_connection_values_and_write_flag(tmp_path: Path) -> None:
    from kp_mcp_bootstrap.registrars import RegistrarError
    with pytest.raises(RegistrarError, match="unsupported_field"):
        server_entry(
            binary_path="/bin/snow-kit",
            config_path=tmp_path / "config.env",
            env={"SNOW_KIT_ACCOUNT": "must-not-be-embedded"},
        )
    from kp_mcp_bootstrap.registrars import RegistrarError
    with pytest.raises(RegistrarError, match="unsupported_field"):
        server_entry(
            binary_path="/bin/snow-kit",
            config_path=tmp_path / "config.env",
            env={"SNOW_KIT_ENABLE_WRITE": "1"},
        )


def test_offline_doctor_reports_unknown_registration_authority(tmp_path, monkeypatch):
    config = tmp_path / "config.env"
    config.write_text("SNOW_KIT_ACCOUNT=example\n")
    config.chmod(0o600)
    monkeypatch.setattr("snow_kit.bootstrap.default_platform_paths", lambda: {
        host: tmp_path / host / "config" for host in ("cursor", "codex", "claude")
    })
    result = doctor(binary_path=sys.executable, config_path=config)
    assert result["ready"] is False
    assert result["checks"]["registrations"]["ok"] is False
    assert result["checks"]["write_posture"]["mode"] == "fail-closed-read-only"

def test_live_doctor_accepts_standard_snow_kit_data_envelope() -> None:
    result = SimpleNamespace(
        isError=False,
        content=[SimpleNamespace(text='{"data":{"rows":[{"1":1}]},"meta":{},"warnings":[]}')],
    )

    _assert_live_tool_success(result, "SELECT 1")


@pytest.mark.parametrize(
    "payload",
    [
        '{"error":{"code":"AUTH"}}',
        '{"status":"error"}',
        '{"meta":{},"warnings":[]}',
    ],
)
def test_live_doctor_rejects_error_or_unknown_envelopes(payload: str) -> None:
    result = SimpleNamespace(isError=False, content=[SimpleNamespace(text=payload)])

    with pytest.raises(RuntimeError):
        _assert_live_tool_success(result, "SELECT 1")


@pytest.mark.parametrize("verb", ["setup", "repair"])
@pytest.mark.parametrize("dry_run", [False, True])
def test_profile_lifecycle_refuses_before_ancillary_work(tmp_path, monkeypatch, verb, dry_run):
    from snow_kit import bootstrap as lifecycle
    from kp_mcp_bootstrap.registrars import RegistrarError, ReasonCode

    monkeypatch.setattr(lifecycle, "default_platform_paths", lambda: {
        host: tmp_path / host / "config" for host in ("cursor", "codex", "claude")
    })
    def forbidden(*args, **kwargs):
        pytest.fail("profile action happened before registration authority was checked")
    monkeypatch.setattr(lifecycle, "write_profile", forbidden)
    monkeypatch.setattr(lifecycle, "repair_profile", forbidden)
    monkeypatch.setattr(lifecycle, "resolve_snowflake_user", forbidden)
    with pytest.raises(RegistrarError) as caught:
        getattr(lifecycle, verb)(config_path=tmp_path / "profile.env", dry_run=dry_run,
                                binary_path="/opt/snow-kit")
    assert caught.value.code is ReasonCode.CONTEXT_REQUIRED
    assert not list(tmp_path.iterdir())
