"""Durable sandbox-mode guardrail (E5) + core↔testkit contract drift guard.

Covers:
  - google_kit.core.sandbox.resolve_profile precedence (explicit > sandbox > default).
  - The guardrail actually steers build_service_for_op's active profile, without
    touching production behavior when sandbox mode is off.
  - The core sandbox-mode env contract agrees with the test-only testkit harness
    (they cannot share code — testkit is kit-agnostic — so the contract is locked
    here to prevent the kind of drift E5 fixed in the harness docstring).
"""
from __future__ import annotations

from typing import Any

import pytest

from google_kit.core.sandbox import (
    SANDBOX_ENV_VAR,
    SANDBOX_PROFILE_VAR,
    is_sandbox_enabled,
    resolve_profile,
    sandbox_profile,
)


class TestResolveProfile:
    def test_explicit_profile_always_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(SANDBOX_ENV_VAR, "1")  # even in sandbox mode
        assert resolve_profile("prod") == "prod"

    def test_sandbox_mode_selects_sandbox_profile(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(SANDBOX_ENV_VAR, "1")
        monkeypatch.delenv(SANDBOX_PROFILE_VAR, raising=False)
        assert resolve_profile(None) == "sandbox"

    def test_sandbox_profile_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(SANDBOX_ENV_VAR, "1")
        monkeypatch.setenv(SANDBOX_PROFILE_VAR, "qa-playground")
        assert resolve_profile(None) == "qa-playground"
        assert sandbox_profile() == "qa-playground"

    def test_off_by_default_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(SANDBOX_ENV_VAR, raising=False)
        assert resolve_profile(None) is None
        assert is_sandbox_enabled() is False

    def test_non_strict_values_do_not_enable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(SANDBOX_ENV_VAR, "true")
        assert is_sandbox_enabled() is False
        assert resolve_profile(None) is None


class TestGuardrailWiredIntoAuth:
    """build_service_for_op must steer the Keychain profile via the guardrail."""

    def _patch_downstream(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
        captured: dict[str, Any] = {}

        class _Cfg:
            profile = "prod-default"

        class _Store:
            def __init__(self, *, profile: str) -> None:
                captured["profile"] = profile

            def get(self, _key: str) -> str:
                return "client-id"

        monkeypatch.setattr("kp_mcp_bootstrap.config.load_config", lambda: _Cfg())
        monkeypatch.setattr("kp_mcp_bootstrap.secrets.KeychainSecretStore", _Store)
        monkeypatch.setattr(
            "google_kit.core.client.build_authorized_service",
            lambda *a, **k: object(),
        )
        return captured

    def test_sandbox_mode_steers_to_sandbox_profile(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = self._patch_downstream(monkeypatch)
        monkeypatch.setenv(SANDBOX_ENV_VAR, "1")
        monkeypatch.delenv(SANDBOX_PROFILE_VAR, raising=False)
        from google_kit.core.auth import build_service_for_op

        build_service_for_op("drive.create")
        assert captured["profile"] == "sandbox"

    def test_sandbox_off_uses_config_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = self._patch_downstream(monkeypatch)
        monkeypatch.delenv(SANDBOX_ENV_VAR, raising=False)
        from google_kit.core.auth import build_service_for_op

        build_service_for_op("drive.create")
        assert captured["profile"] == "prod-default"

    def test_explicit_profile_overrides_sandbox(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = self._patch_downstream(monkeypatch)
        monkeypatch.setenv(SANDBOX_ENV_VAR, "1")
        from google_kit.core.auth import build_service_for_op

        build_service_for_op("drive.create", profile="explicit-prod")
        assert captured["profile"] == "explicit-prod"


class TestCoreTestkitContractParity:
    """Lock the GOOGLE_KIT_SANDBOX contract across core and the testkit harness."""

    def test_env_var_names_match(self) -> None:
        from kp_mcp_testkit import sandbox as tk

        assert SANDBOX_ENV_VAR == tk.SANDBOX_ENV_VAR
        assert SANDBOX_PROFILE_VAR == tk.SANDBOX_PROFILE_VAR

    def test_default_sandbox_profile_matches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from kp_mcp_testkit import sandbox as tk

        monkeypatch.delenv(SANDBOX_PROFILE_VAR, raising=False)
        assert sandbox_profile() == tk.sandbox_profile() == "sandbox"

    @pytest.mark.parametrize("val,expected", [("1", True), ("true", False), ("0", False), ("", False)])
    def test_is_sandbox_enabled_agrees(
        self, monkeypatch: pytest.MonkeyPatch, val: str, expected: bool
    ) -> None:
        from kp_mcp_testkit import sandbox as tk

        monkeypatch.setenv(SANDBOX_ENV_VAR, val)
        assert is_sandbox_enabled() == tk.is_sandbox_enabled() == expected
