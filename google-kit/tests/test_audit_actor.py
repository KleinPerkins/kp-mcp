"""QA #1 regression: the audit ``actor`` must reflect the operating profile.

``core.audit`` defines ``actor`` as "Identity performing the operation
(profile/account)", but every service core fn calls ``execute_api_call`` without
an actor, so the field was hardcoded to ``"default"`` regardless of the
operator's ``--profile`` (CLI) or ``GOOGLE_KIT_PROFILE`` (env). A multi-profile
operator's audit trail therefore could not attribute a mutation to the account
that performed it.

The fix threads the resolved profile into an ``actor`` contextvar (set by the
CLI/MCP boundary, mirroring ``run_id``) which ``execute_api_call`` reads when no
explicit actor is passed.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import google_kit  # noqa: F401 - triggers registration
from google_kit.core.audit import get_actor, read_audit, reset_actor, set_actor
from google_kit.core.client import execute_api_call


def test_execute_api_call_uses_actor_contextvar(tmp_path: Path) -> None:
    audit_file = tmp_path / "audit.jsonl"
    token = set_actor("work")
    try:
        execute_api_call(
            lambda: {"id": "x-1"},
            op="tasks.create",
            posture="write",
            audit_file=audit_file,
        )
    finally:
        reset_actor(token)

    rec = read_audit(op="tasks.create", audit_file=audit_file)[0]
    assert rec["actor"] == "work"


def test_explicit_actor_still_wins_over_contextvar(tmp_path: Path) -> None:
    audit_file = tmp_path / "audit.jsonl"
    token = set_actor("work")
    try:
        execute_api_call(
            lambda: {"id": "x-1"},
            op="tasks.create",
            posture="write",
            actor="explicit",
            audit_file=audit_file,
        )
    finally:
        reset_actor(token)

    rec = read_audit(op="tasks.create", audit_file=audit_file)[0]
    assert rec["actor"] == "explicit"


def test_actor_defaults_to_default_when_unset(tmp_path: Path) -> None:
    audit_file = tmp_path / "audit.jsonl"
    execute_api_call(
        lambda: {"id": "x-1"},
        op="tasks.create",
        posture="write",
        audit_file=audit_file,
    )
    rec = read_audit(op="tasks.create", audit_file=audit_file)[0]
    assert rec["actor"] == "default"


# ─── Boundary wiring: build_service_for_op sets the actor ────────────────────


def _patch_auth_downstream(monkeypatch: pytest.MonkeyPatch, *, cfg_profile: str) -> None:
    """Mirror test_sandbox_mode's downstream patches so build_service_for_op runs."""

    class _Cfg:
        profile = cfg_profile

    class _Store:
        def __init__(self, *, profile: str) -> None:
            del profile

        def get(self, _key: str) -> str:
            return "client-id"

    monkeypatch.setattr("kp_mcp_bootstrap.config.load_config", lambda: _Cfg())
    monkeypatch.setattr("kp_mcp_bootstrap.secrets.KeychainSecretStore", _Store)
    monkeypatch.setattr(
        "google_kit.core.client.build_authorized_service", lambda *a, **k: object()
    )


def test_build_service_for_op_sets_actor_to_explicit_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from google_kit.core.auth import build_service_for_op

    _patch_auth_downstream(monkeypatch, cfg_profile="prod-default")
    token = set_actor("default")  # establish a known baseline to reset to
    try:
        build_service_for_op("drive.create", profile="work")
        assert get_actor() == "work"
    finally:
        reset_actor(token)


def test_build_service_for_op_sets_actor_to_config_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from google_kit.core.auth import build_service_for_op

    monkeypatch.delenv("GOOGLE_KIT_SANDBOX", raising=False)
    _patch_auth_downstream(monkeypatch, cfg_profile="prod-default")
    token = set_actor("default")
    try:
        build_service_for_op("drive.create")
        assert get_actor() == "prod-default"
    finally:
        reset_actor(token)
