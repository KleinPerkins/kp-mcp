"""Legacy registrar compatibility under explicit v1 ownership and approval."""

import base64
import json
import tomllib
from pathlib import Path

import pytest

from kp_mcp_bootstrap.errors import BootstrapError
from kp_mcp_bootstrap.registrars import (
    ClaudeRegistrar, CodexRegistrar, CursorRegistrar, Inspection, Outcome,
    ReasonCode, RecoveryDisposition, RegistrarError, RegistrationDefinition, SourceIdentity,
    fixture_approval, fixture_context,
)
from kp_mcp_bootstrap.registrars.base import BaseRegistrar, ServerEntry

ENTRY = ServerEntry(command="/usr/local/bin/google-kit", args=["mcp"])
IDENTITY = SourceIdentity("KleinPerkins/kp-mcp", "kp-mcp:google-kit", "a" * 40, "google-kit")


@pytest.fixture(params=[CursorRegistrar, CodexRegistrar, ClaudeRegistrar])
def target(request, tmp_path):
    registrar = request.param()
    definition = RegistrationDefinition.from_server_entry(IDENTITY, ENTRY)
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        yield registrar, fixture, definition


def servers(path):
    if path.suffix == ".toml":
        return tomllib.loads(path.read_text()).get("mcp_servers", {})
    return json.loads(path.read_text()).get("mcpServers", {})


def seed_sibling(path):
    if path.suffix == ".toml":
        path.write_text('# keep this comment\n[mcp_servers.other]\ncommand = "/other"\n')
    else:
        path.write_text(json.dumps({"mcpServers": {"other": {"command": "/other"}}}))


def apply_legacy(registrar, fixture, definition):
    operation = registrar.prepare(registrar.preview(fixture.config_path, definition, context=fixture.context))
    return registrar.register(fixture.config_path, ENTRY, context=fixture.context,
                              prepared=operation, approval=fixture_approval(operation))


def snapshot(root):
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_legacy_constructor_and_import_remain_compatible():
    for args in (None, []):
        assert ServerEntry("/fixture", args=args).args == ["mcp"]
    assert issubclass(CursorRegistrar, BaseRegistrar)
    assert issubclass(RegistrarError, BootstrapError)


def test_creates_exact_stdio_entry_with_explicit_approval(target):
    registrar, fixture, definition = target
    assert registrar.would_register(fixture.config_path, ENTRY, context=fixture.context) is True
    assert apply_legacy(registrar, fixture, definition) is True
    actual = servers(fixture.config_path)["google-kit"]
    assert actual["command"] == ENTRY.command
    assert actual["args"] == ["mcp"]
    if isinstance(registrar, ClaudeRegistrar):
        assert actual["type"] == "stdio"


def test_idempotent_register_has_no_new_backup_or_receipt(target):
    registrar, fixture, definition = target
    assert apply_legacy(registrar, fixture, definition) is True
    before = snapshot(fixture.root)
    assert registrar.register(fixture.config_path, ENTRY, context=fixture.context) is False
    assert registrar.would_register(fixture.config_path, ENTRY, context=fixture.context) is False
    assert snapshot(fixture.root) == before
    assert not list(fixture.root.glob("*.bak.*"))


def test_preserves_siblings_and_saves_exact_private_preimage(target):
    registrar, fixture, definition = target
    seed_sibling(fixture.config_path)
    original = fixture.config_path.read_bytes()
    operation = registrar.prepare(registrar.preview(fixture.config_path, definition, context=fixture.context))
    assert fixture.config_path.read_bytes() == original
    record = json.loads((fixture.state_directory / f"prepared-{operation.record_id}.json").read_bytes())
    assert base64.b64decode(record["config_preimage"]) == original
    assert registrar.register(fixture.config_path, ENTRY, context=fixture.context,
                              prepared=operation, approval=fixture_approval(operation)) is True
    assert servers(fixture.config_path)["other"] == {"command": "/other"}
    assert "google-kit" in servers(fixture.config_path)
    if fixture.config_path.suffix == ".toml":
        assert "# keep this comment" in fixture.config_path.read_text()
    assert not list(fixture.root.glob("*.bak.*"))
    assert fixture.state_directory.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in fixture.state_directory.iterdir())


def test_unregister_requires_approved_removal_then_is_idempotent(target):
    registrar, fixture, definition = target
    assert apply_legacy(registrar, fixture, definition) is True
    with pytest.raises(RegistrarError) as caught:
        registrar.unregister(fixture.config_path, context=fixture.context)
    assert caught.value.code is ReasonCode.PREPARED_RECORD_REQUIRED
    operation = registrar.prepare(registrar.preview_unregister(fixture.config_path, context=fixture.context))
    assert registrar.unregister(fixture.config_path, context=fixture.context,
                                prepared=operation, approval=fixture_approval(operation)) is True
    assert "google-kit" not in servers(fixture.config_path)
    before = snapshot(fixture.root)
    assert registrar.unregister(fixture.config_path, context=fixture.context) is False
    assert snapshot(fixture.root) == before


@pytest.mark.parametrize("existing_file", [False, True])
def test_missing_entry_unregister_without_context_only_proves_absence(target, existing_file):
    registrar, fixture, _definition = target
    if existing_file:
        seed_sibling(fixture.config_path)
    before = snapshot(fixture.root)
    assert registrar.unregister(fixture.config_path) is False
    assert snapshot(fixture.root) == before


@pytest.mark.parametrize("method", ["register", "would_register", "current_entry"])
@pytest.mark.parametrize("owned", [False, True])
def test_context_required_for_every_legacy_read_or_registration(target, method, owned):
    registrar, fixture, definition = target
    if owned:
        apply_legacy(registrar, fixture, definition)
    before = snapshot(fixture.root)
    args = (fixture.config_path, ENTRY) if method != "current_entry" else (fixture.config_path,)
    with pytest.raises(RegistrarError) as caught:
        getattr(registrar, method)(*args)
    assert caught.value.code is ReasonCode.CONTEXT_REQUIRED
    assert snapshot(fixture.root) == before


def test_missing_approval_cannot_create_config_or_state(target):
    registrar, fixture, _definition = target
    before = snapshot(fixture.root)
    with pytest.raises(RegistrarError) as caught:
        registrar.register(fixture.config_path, ENTRY, context=fixture.context)
    assert caught.value.code is ReasonCode.PREPARED_RECORD_REQUIRED
    assert snapshot(fixture.root) == before


def test_equal_unreceipted_entry_requires_adoption(target):
    registrar, fixture, definition = target
    assert apply_legacy(registrar, fixture, definition) is True
    for path in fixture.state_directory.glob("receipt-*.json"):
        path.unlink()
    before = snapshot(fixture.root)
    with pytest.raises(RegistrarError) as caught:
        registrar.register(fixture.config_path, ENTRY, context=fixture.context)
    assert caught.value.code is ReasonCode.OWNERSHIP_UNKNOWN
    assert snapshot(fixture.root) == before


def test_current_entry_is_bounded_inspection_and_runtime_unknown(target):
    registrar, fixture, definition = target
    assert apply_legacy(registrar, fixture, definition) is True
    inspection = registrar.current_entry(fixture.config_path, context=fixture.context)
    assert isinstance(inspection, Inspection)
    assert inspection.present and inspection.owned_projection_match
    public = inspection.to_dict()
    assert ENTRY.command not in json.dumps(public)
    for name in ("enabled", "authenticated", "tools_discovered", "safe_read"):
        assert public["observations"][name]["status"] == "unknown"


@pytest.mark.parametrize("method", ["register", "unregister"])
@pytest.mark.parametrize("outcome,changed", [(Outcome.FAILED, False), (Outcome.RECOVERY_REQUIRED, True)])
def test_failed_apply_cannot_be_reported_as_legacy_no_change(target, monkeypatch, method, outcome, changed):
    registrar, fixture, definition = target
    if method == "unregister":
        apply_legacy(registrar, fixture, definition)
        preview = registrar.preview_unregister(fixture.config_path, context=fixture.context)
    else:
        preview = registrar.preview(fixture.config_path, definition, context=fixture.context)
    original = snapshot(fixture.root)
    operation = registrar.prepare(preview)
    from kp_mcp_bootstrap.registrars.transactions import _failed_result
    failure = _failed_result(operation, ReasonCode.WRITE_FAILED, outcome=outcome, config_changed=changed)
    monkeypatch.setattr(registrar, "apply", lambda *_args: failure)
    with pytest.raises(RegistrarError) as caught:
        args = (fixture.config_path, ENTRY) if method == "register" else (fixture.config_path,)
        getattr(registrar, method)(*args, context=fixture.context,
                                  prepared=operation, approval=fixture_approval(operation))
    assert caught.value.code is ReasonCode.WRITE_FAILED
    after = snapshot(fixture.root)
    assert all(after[path] == data for path, data in original.items())
    assert fixture.config_path.exists() is (method == "unregister")


@pytest.mark.parametrize("method", ["register", "would_register", "unregister"])
def test_legacy_methods_refuse_owned_field_drift_without_writes(target, method):
    registrar, fixture, definition = target
    apply_legacy(registrar, fixture, definition)
    raw = fixture.config_path.read_text().replace(ENTRY.command, "/operator/change")
    fixture.config_path.write_text(raw)
    before = snapshot(fixture.root)
    args = (fixture.config_path,) if method == "unregister" else (fixture.config_path, ENTRY)
    with pytest.raises(RegistrarError) as caught:
        getattr(registrar, method)(*args, context=fixture.context)
    assert caught.value.code in {ReasonCode.OWNED_FIELD_DRIFT, ReasonCode.REMOVAL_CONFLICT}
    assert snapshot(fixture.root) == before
    inspection = registrar.current_entry(fixture.config_path, context=fixture.context)
    assert inspection.owned_projection_match is False
    assert ReasonCode.OWNED_FIELD_DRIFT in inspection.reason_codes


@pytest.mark.parametrize("method", ["register", "unregister"])
def test_recovered_original_operation_replays_as_legacy_no_change(target, method):
    registrar, fixture, definition = target
    if method == "unregister":
        apply_legacy(registrar, fixture, definition)
        preview = registrar.preview_unregister(fixture.config_path, context=fixture.context)
    else:
        preview = registrar.preview(fixture.config_path, definition, context=fixture.context)
    operation = registrar.prepare(preview)
    approval = fixture_approval(operation)
    def interrupt(step):
        if step == "journal_prepared":
            raise RuntimeError("fixture interruption")
    registrar._fault = interrupt
    assert registrar.apply(operation, approval).outcome is Outcome.RECOVERY_REQUIRED
    registrar._fault = lambda _step: None
    recovery = registrar.prepare_recovery(operation, RecoveryDisposition.COMPLETE)
    result = registrar.recover(recovery, RecoveryDisposition.COMPLETE, fixture_approval(recovery))
    assert result.outcome is Outcome.RECOVERED
    registered = result.to_dict()["observations"]["registered"]["status"]
    assert registered == ("fail" if method == "unregister" else "pass")
    before = snapshot(fixture.root)
    args = (fixture.config_path, ENTRY) if method == "register" else (fixture.config_path,)
    assert getattr(registrar, method)(*args, context=fixture.context,
                                     prepared=operation, approval=approval) is False
    assert snapshot(fixture.root) == before


@pytest.mark.parametrize("native_name", ["service.with.dots", 'service "quoted"', "service/with~escape"])
def test_codex_quoted_native_name_remains_one_key_across_update_and_removal(tmp_path, native_name):
    from dataclasses import replace

    registrar = CodexRegistrar()
    identity = replace(IDENTITY, native_name=native_name)
    definition = RegistrationDefinition.stdio(identity, command="/opt/fixtures/first", args=())
    sibling = '# retained sibling comment\n[mcp_servers."sibling.with.dots"]\ncommand = "/other" # retained inline\n'
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        fixture.config_path.write_text(sibling)
        operation = registrar.prepare(registrar.preview(fixture.config_path, definition, context=fixture.context))
        assert registrar.apply(operation, fixture_approval(operation)).outcome is Outcome.APPLIED
        data = servers(fixture.config_path)
        assert set(data) == {"sibling.with.dots", native_name}
        assert data[native_name] == {"command": "/opt/fixtures/first", "args": []}
        assert sibling in fixture.config_path.read_text()

        updated = RegistrationDefinition.stdio(replace(identity, source_revision="b" * 40), command="/opt/fixtures/second", args=("mcp",))
        context = replace(fixture.context, source_revision=updated.source_revision, definition_digest=updated.digest)
        operation = registrar.prepare(registrar.preview(fixture.config_path, updated, context=context))
        assert registrar.apply(operation, fixture_approval(operation)).outcome is Outcome.APPLIED
        data = servers(fixture.config_path)
        assert set(data) == {"sibling.with.dots", native_name}
        assert data[native_name] == {"command": "/opt/fixtures/second", "args": ["mcp"]}
        assert sibling in fixture.config_path.read_text()

        operation = registrar.prepare(registrar.preview_unregister(fixture.config_path, context=context))
        assert registrar.apply(operation, fixture_approval(operation)).outcome is Outcome.APPLIED
        assert servers(fixture.config_path) == {"sibling.with.dots": {"command": "/other"}}
        remaining = fixture.config_path.read_text()
        assert remaining.startswith(sibling)
        assert not remaining[len(sibling):].strip()
