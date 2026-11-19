"""Tests for kp_mcp_bootstrap.detect."""

from pathlib import Path

import pytest

from kp_mcp_bootstrap.detect import detect


def test_no_configs_present(tmp_path: Path) -> None:
    result = detect(home=tmp_path)
    assert result.home == tmp_path
    assert result.cursor_config is None
    assert result.codex_config is None
    assert result.claude_config is None


def test_cursor_config_detected(tmp_path: Path) -> None:
    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir()
    mcp_json = cursor_dir / "mcp.json"
    mcp_json.write_text("{}")

    result = detect(home=tmp_path)
    assert result.cursor_config == mcp_json
    assert result.codex_config is None
    assert result.claude_config is None


def test_codex_config_detected(tmp_path: Path) -> None:
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    cfg = codex_dir / "config.toml"
    cfg.write_text("")

    result = detect(home=tmp_path)
    assert result.codex_config == cfg
    assert result.cursor_config is None


def test_claude_config_detected(tmp_path: Path) -> None:
    claude_json = tmp_path / ".claude.json"
    claude_json.write_text("{}")

    result = detect(home=tmp_path)
    assert result.claude_config == claude_json


def test_all_configs_detected(tmp_path: Path) -> None:
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".cursor" / "mcp.json").write_text("{}")
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "config.toml").write_text("")
    (tmp_path / ".claude.json").write_text("{}")

    result = detect(home=tmp_path)
    assert result.cursor_config is not None
    assert result.codex_config is not None
    assert result.claude_config is not None
    assert set(result.platform_configs.keys()) == {"cursor", "codex", "claude"}


def test_is_macos_is_bool(tmp_path: Path) -> None:
    result = detect(home=tmp_path)
    assert isinstance(result.is_macos, bool)
