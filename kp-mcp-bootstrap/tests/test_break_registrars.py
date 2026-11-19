"""Adversarial registrar contracts using only disposable fixture authority.

Retain the original secret, atomic-write, stable-link, malformed-input, sibling,
and idempotency coverage while exercising explicit preview/prepare/apply.
"""

import json
import os
import tomllib
from pathlib import Path

import pytest

from kp_mcp_bootstrap.registrars import (
    ClaudeRegistrar, CodexRegistrar, CursorRegistrar, Outcome, ReasonCode,
    RegistrarError, RegistrationDefinition, SourceIdentity, fixture_approval,
    fixture_context,
)
from kp_mcp_bootstrap.registrars.base import ServerEntry

SECRET = "sk-LEAKED-SECRET-TOKEN-DO-NOT-PERSIST"
ENTRY = ServerEntry(command="/usr/local/bin/google-kit", args=["mcp"],
                    env={"GOOGLE_KIT_CONFIG_DIR": "/tmp/cfg"})
IDENTITY = SourceIdentity("KleinPerkins/kp-mcp", "kp-mcp:google-kit", "a" * 40, "google-kit")


@pytest.fixture(autouse=True)
def secrets_in_env(monkeypatch):
    for key in ("GOOGLE_KIT_CLIENT_SECRET", "ACCESS_TOKEN", "REFRESH_TOKEN"):
        monkeypatch.setenv(key, SECRET)


@pytest.fixture(params=[CursorRegistrar, CodexRegistrar, ClaudeRegistrar])
def target(request, tmp_path):
    registrar = request.param()
    definition = RegistrationDefinition.from_server_entry(IDENTITY, ENTRY)
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        yield registrar, fixture, definition


def seed(path, *, secret=False):
    if path.suffix == ".toml":
        text = '# retained comment\n[mcp_servers.keep]\ncommand = "/keep"\nargs = ["x"]\n'
        if secret:
            text += f'token = "{SECRET}"\n'
        path.write_text(text)
    else:
        sibling = {"command": "/keep", "args": ["x"]}
        if secret:
            sibling["token"] = SECRET
        path.write_text(json.dumps({"mcpServers": {"keep": sibling}}, indent=2) + "\n")


def entries(path):
    if path.suffix == ".toml":
        return tomllib.loads(path.read_text())["mcp_servers"]
    return json.loads(path.read_text())["mcpServers"]


def prepare(target):
    registrar, fixture, definition = target
    preview = registrar.preview(fixture.config_path, definition, context=fixture.context)
    operation = registrar.prepare(preview)
    return preview, operation, fixture_approval(operation)


def test_environment_secrets_are_not_invented_in_config_or_public_results(target):
    registrar, fixture, _definition = target
    preview, operation, approval = prepare(target)
    result = registrar.apply(operation, approval)
    assert result.outcome is Outcome.APPLIED
    contents = fixture.config_path.read_text()
    assert "/tmp/cfg" in contents
    assert SECRET not in contents
    for key in ("client_secret", "refresh_token", "access_token"):
        assert key not in contents
    public = [preview.to_dict(), operation.to_dict(), result.to_dict(),
              registrar.current_entry(fixture.config_path, context=fixture.context).to_dict()]
    assert SECRET not in json.dumps(public)


def test_explicit_secret_env_definition_is_rejected_without_echo_or_state(tmp_path):
    entry = ServerEntry("/opt/fixture", env={"ACCESS_TOKEN": SECRET})
    with pytest.raises((RegistrarError, ValueError)) as caught:
        RegistrationDefinition.from_server_entry(IDENTITY, entry)
    assert SECRET not in str(caught.value)
    assert not list(tmp_path.iterdir())


def test_failed_target_rename_preserves_original_and_cleans_staging(target, monkeypatch):
    registrar, fixture, _definition = target
    seed(fixture.config_path)
    original = fixture.config_path.read_bytes()
    _preview, operation, approval = prepare(target)
    real_replace = os.replace
    def fail_target_only(source, destination):
        if Path(destination) == fixture.config_path:
            raise OSError("synthetic target rename failure")
        return real_replace(source, destination)
    monkeypatch.setattr("kp_mcp_bootstrap.registrars.state.os.replace", fail_target_only)
    result = registrar.apply(operation, approval)
    assert result.outcome is Outcome.RECOVERY_REQUIRED
    assert result.config_changed is False
    assert fixture.config_path.read_bytes() == original
    assert not list(fixture.root.rglob("*.tmp"))
    assert not list(fixture.root.glob("*.bak.*"))
    assert "synthetic target rename failure" not in json.dumps(result.to_dict())


def test_stable_leaf_symlink_within_fixture_is_preserved(target):
    registrar, fixture, _definition = target
    real_dir = fixture.root / "actual"
    real_dir.mkdir(mode=0o700)
    actual = real_dir / fixture.config_path.name
    seed(actual)
    fixture.config_path.symlink_to(actual)
    _preview, operation, approval = prepare(target)
    result = registrar.apply(operation, approval)
    assert result.outcome is Outcome.APPLIED
    assert fixture.config_path.is_symlink()
    assert fixture.config_path.resolve() == actual
    data = entries(actual)
    assert data["keep"] == {"command": "/keep", "args": ["x"]}
    assert "google-kit" in data


def test_malformed_config_refuses_without_backup_or_clobber(target):
    registrar, fixture, definition = target
    fixture.config_path.write_text("this is = = not toml" if fixture.config_path.suffix == ".toml"
                                   else "{ this is : not json ]")
    original = fixture.config_path.read_bytes()
    before = set(fixture.state_directory.iterdir())
    with pytest.raises(RegistrarError) as caught:
        registrar.preview(fixture.config_path, definition, context=fixture.context)
    assert caught.value.code is ReasonCode.MALFORMED_CONFIG
    assert fixture.config_path.read_bytes() == original
    assert set(fixture.state_directory.iterdir()) == before
    assert not list(fixture.root.glob("*.bak.*"))
    assert str(fixture.config_path) not in str(caught.value)


def test_unrelated_secret_sibling_is_preserved_but_never_disclosed(target):
    registrar, fixture, definition = target
    seed(fixture.config_path, secret=True)
    expected = entries(fixture.config_path)["keep"]
    preview, operation, approval = prepare(target)
    result = registrar.apply(operation, approval)
    assert result.outcome is Outcome.APPLIED
    assert entries(fixture.config_path)["keep"] == expected
    assert "google-kit" in entries(fixture.config_path)
    inspection = registrar.inspect_registration(fixture.config_path, context=fixture.context)
    assert SECRET not in json.dumps([preview.to_dict(), operation.to_dict(), result.to_dict(), inspection.to_dict()])
    assert not list(fixture.root.glob("*.bak.*"))


def test_double_register_has_no_duplicate_or_new_private_backup(target):
    registrar, fixture, _definition = target
    _preview, operation, approval = prepare(target)
    assert registrar.register(fixture.config_path, ENTRY, context=fixture.context,
                              prepared=operation, approval=approval) is True
    before = {path.name: path.read_bytes() for path in fixture.state_directory.iterdir()}
    assert registrar.register(fixture.config_path, ENTRY, context=fixture.context) is False
    assert {path.name: path.read_bytes() for path in fixture.state_directory.iterdir()} == before
    assert list(entries(fixture.config_path)) == ["google-kit"]
