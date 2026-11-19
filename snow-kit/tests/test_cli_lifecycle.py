"""Lifecycle CLI adaptation tests."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from snow_kit.cli import _lifecycle


def test_setup_collects_repeated_context_paths(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, Any] = {}

    def fake_setup(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"state": "needs_sign_in"}

    monkeypatch.setattr("snow_kit.bootstrap.setup", fake_setup)

    result = _lifecycle(
        "setup",
        [
            "--account",
            "account",
            "--user",
            "operator",
            "--context-repo",
            "/approved/repo",
            "--context-path",
            "business-context/**/*.md",
            "--context-path",
            "metrics/*.md",
            "--context-mode",
            "strict",
            "--config",
            "/private/config.env",
        ],
    )

    assert result == 0
    assert captured["profile_values"] == {
        "SNOW_KIT_ACCOUNT": "account",
        "SNOW_KIT_USER": "operator",
    }
    assert captured["context_repo"] == Path("/approved/repo")
    assert captured["context_paths"] == (
        "business-context/**/*.md",
        "metrics/*.md",
    )
    assert captured["context_mode"] == "strict"
    assert captured["config_path"] == Path("/private/config.env")
    assert json.loads(capsys.readouterr().out)["state"] == "needs_sign_in"


def test_incomplete_setup_returns_actionable_state(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "snow_kit.bootstrap.setup",
        lambda **_kwargs: {"state": "needs_setup"},
    )

    result = _lifecycle("setup", [])

    assert result == 0
    assert json.loads(capsys.readouterr().out)["state"] == "needs_setup"


@pytest.mark.parametrize("verb", ["setup", "bootstrap", "repair", "unregister"])
def test_cli_refuses_registration_before_any_side_effect(tmp_path, monkeypatch, capsys, verb):
    from snow_kit.cli import main
    monkeypatch.setattr("snow_kit.bootstrap.default_platform_paths", lambda: {
        host: tmp_path / host / "config" for host in ("cursor", "codex", "claude")
    })
    assert main([verb, "--config", str(tmp_path / "profile.env")]) == 1
    output = capsys.readouterr()
    assert json.loads(output.err)["reason_codes"] == ["context_required"]
    assert str(tmp_path) not in output.err
    assert not list(tmp_path.iterdir())
