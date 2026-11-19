"""Security and precedence tests for the canonical operator-local profile."""
from __future__ import annotations

import os
from importlib.resources import files
from pathlib import Path

import pytest

from snow_kit.core.config import (
    CONFIG_PATH_ENV,
    CONTEXT_ALLOW_PATHS_KEY,
    ConfigError,
    SnowKitConfig,
    load_profile,
    repair_profile,
    write_profile,
)


def _profile(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    return path


def test_profile_precedence_and_typed_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _profile(
        tmp_path / "config.env",
        "\n".join(
            [
                "SNOW_KIT_ACCOUNT=profile-account",
                "SNOW_KIT_DATABASE=profile-db",
                "SNOW_KIT_MAX_RESULT_ROWS=42",
                "SNOW_KIT_MAX_RECONNECT_RETRIES=3",
            ]
        )
        + "\n",
    )
    monkeypatch.setenv(CONFIG_PATH_ENV, str(path))
    monkeypatch.setenv("SNOW_KIT_ACCOUNT", "process-account")

    config = SnowKitConfig.from_env()

    assert config.account == "process-account"
    assert config.database == "profile-db"
    assert config.max_result_rows == 42
    assert config.max_reconnect_retries == 3


def test_neutral_defaults_have_no_affirm_connection_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CONFIG_PATH_ENV, str(tmp_path / "missing.env"))
    for key in (
        "SNOW_KIT_ACCOUNT",
        "SNOWFLAKE_ACCOUNT",
        "SNOW_KIT_DATABASE",
        "SNOWFLAKE_DATABASE",
        "SNOW_KIT_WAREHOUSE",
        "SNOWFLAKE_WAREHOUSE",
    ):
        monkeypatch.delenv(key, raising=False)

    config = SnowKitConfig.from_env()

    assert config.account is None
    assert config.database is None
    assert config.warehouse is None


@pytest.mark.parametrize(
    "content",
    [
        "UNKNOWN_KEY=value\n",
        "SNOW_KIT_ENABLE_WRITE=1\n",
        "SNOW_KIT_MAX_RESULT_ROWS=not-an-int\n",
    ],
)
def test_profile_rejects_unsupported_or_invalid_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    content: str,
) -> None:
    path = _profile(tmp_path / "config.env", content)
    monkeypatch.setenv(CONFIG_PATH_ENV, str(path))

    with pytest.raises((ConfigError, ValueError)):
        SnowKitConfig.from_env()


def test_profile_rejects_group_readable_file(tmp_path: Path) -> None:
    path = _profile(tmp_path / "config.env", "SNOW_KIT_ACCOUNT=example\n")
    path.chmod(0o640)

    with pytest.raises(ConfigError, match="0600"):
        load_profile(path)


def test_profile_rejects_symlink(tmp_path: Path) -> None:
    target = _profile(tmp_path / "target.env", "SNOW_KIT_ACCOUNT=example\n")
    link = tmp_path / "config.env"
    os.symlink(target, link)

    with pytest.raises(ConfigError, match="non-symlink"):
        load_profile(link)


def test_config_path_must_be_absolute(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CONFIG_PATH_ENV, "relative/config.env")

    with pytest.raises(ConfigError, match="absolute"):
        SnowKitConfig.from_env()


def test_permission_spec_path_must_be_absolute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _profile(
        tmp_path / "config.env",
        "SNOW_KIT_PERMISSION_SPEC_PATH=relative/spec\n",
    )
    monkeypatch.setenv(CONFIG_PATH_ENV, str(path))

    with pytest.raises(ConfigError, match="absolute"):
        SnowKitConfig.from_env()


def test_versioned_context_profile_is_atomic_and_private(tmp_path: Path) -> None:
    path = tmp_path / "snow-kit" / "config.env"

    result = write_profile(
        {
            "SNOW_KIT_ACCOUNT": "example",
            "SNOW_KIT_CONTEXT_REPO": str(tmp_path),
            CONTEXT_ALLOW_PATHS_KEY: '["business-context/**/*.md"]',
            "SNOW_KIT_CONTEXT_MODE": "strict",
        },
        path=path,
    )
    config = SnowKitConfig.from_env(config_path=path)

    assert result["version"] == 1
    assert path.stat().st_mode & 0o777 == 0o600
    assert config.profile_version == 1
    assert config.context_repo == tmp_path
    assert config.context_allow_paths == ("business-context/**/*.md",)
    assert config.context_mode == "strict"
    assert not list(path.parent.glob(".config.env.*"))


@pytest.mark.parametrize(
    "value",
    [
        '["../private.md"]',
        '["/absolute.md"]',
        '["business-context/data.csv"]',
    ],
)
def test_context_allow_paths_reject_unsafe_values(tmp_path: Path, value: str) -> None:
    with pytest.raises(ConfigError):
        write_profile(
            {CONTEXT_ALLOW_PATHS_KEY: value},
            path=tmp_path / "config.env",
        )


def test_repair_normalizes_profile_permissions(tmp_path: Path) -> None:
    path = tmp_path / "config.env"
    path.write_text("SNOW_KIT_ACCOUNT=example\n", encoding="utf-8")
    path.chmod(0o644)

    repair_profile(path)

    assert path.stat().st_mode & 0o777 == 0o600
    assert load_profile(path)["SNOW_KIT_PROFILE_VERSION"] == "1"


def test_repair_dry_run_does_not_change_permissions(tmp_path: Path) -> None:
    path = tmp_path / "config.env"
    path.write_text("SNOW_KIT_ACCOUNT=example\n", encoding="utf-8")
    path.chmod(0o644)

    result = repair_profile(path, dry_run=True)

    assert result["state"] == "would_update"
    assert path.stat().st_mode & 0o777 == 0o644


def test_generic_profile_template_is_packaged_without_local_values() -> None:
    text = files("snow_kit.data").joinpath("config.env.template").read_text(
        encoding="utf-8"
    )

    assert "SNOW_KIT_PROFILE_VERSION=1" in text
    assert "/Users/" not in text
    assert "SNOW_KIT_ENABLE_WRITE" not in text


def test_runtime_diagnostics_redact_connection_identity() -> None:
    config = SnowKitConfig(
        user="person@example.invalid",
        account="private-account",
        database="PRIVATE_DB",
    )

    diagnostics = str(config.redacted())

    assert "person@example.invalid" not in diagnostics
    assert "private-account" not in diagnostics
    assert "PRIVATE_DB" not in diagnostics
