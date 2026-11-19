"""Registrar-v1 secret egress, approval, and writer admission tests."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

import kp_mcp_bootstrap.registrars.writer_window as registrar_writer_window
import kp_mcp_bootstrap.registrars.transactions as registrar_transactions

from kp_mcp_bootstrap.registrars import (
    AuthBinding,
    AuthKind,
    CursorRegistrar,
    MigrationEvidence,
    Outcome,
    ReasonCode,
    RegistrarError,
    RegistrationDefinition,
    SourceIdentity,
    fixture_approval,
    fixture_context,
)
from kp_mcp_bootstrap.registrars.contracts import (
    digest_bytes,
    digest_value,
    isoformat,
)
from kp_mcp_bootstrap.registrars.state import StateStore, inspect_target


SECRET = "sk-synthetic-secret-must-not-egress"


def _definition() -> RegistrationDefinition:
    return RegistrationDefinition.stdio(
        SourceIdentity(
            source_owner="KleinPerkins/kp-mcp",
            connection_id="kp-mcp:security-fixture",
            source_revision="c" * 40,
            native_name="security-fixture",
        ),
        command="/opt/fixtures/security",
        env={"FIXTURE_CONFIG_DIR": "/tmp/security"},
    )


def test_unrelated_sibling_secret_is_preserved_but_never_public(
    tmp_path: Path,
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        fixture.config_path.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "unrelated": {
                            "headers": {"Authorization": f"Bearer {SECRET}"}
                        }
                    }
                }
            )
        )
        preview = registrar.preview(
            fixture.config_path, definition, context=fixture.context
        )
        assert SECRET not in json.dumps(preview.to_dict())
        prepared = registrar.prepare(preview)
        result = registrar.apply(prepared, fixture_approval(prepared))
        assert SECRET not in json.dumps(result.to_dict())
        assert SECRET in fixture.config_path.read_text()


def test_selected_literal_auth_blocks_without_disclosure(tmp_path: Path) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        fixture.config_path.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        definition.native_name: {
                            "command": "/opt/fixtures/security",
                            "args": ["mcp"],
                            "headers": {"Authorization": f"Bearer {SECRET}"},
                        }
                    }
                }
            )
        )
        before = fixture.config_path.read_bytes()
        preview = registrar.preview(
            fixture.config_path, definition, context=fixture.context
        )
        assert ReasonCode.EXISTING_AUTH_MATERIAL in preview.conflicts
        assert SECRET not in json.dumps(preview.to_dict())
        with pytest.raises(RegistrarError) as caught:
            registrar.prepare(preview)
        assert SECRET not in str(caught.value)
        assert fixture.config_path.read_bytes() == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("action_digest", "0" * 64),
        ("prepared_payload_digest", "0" * 64),
        ("issuer_authority", "unrecognized-fixture-issuer"),
        ("choice", "reuse"),
    ],
)
def test_tampered_approval_never_writes(
    field: str, value: str, tmp_path: Path
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        prepared = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )
        approval = replace(fixture_approval(prepared), **{field: value})
        with pytest.raises(RegistrarError) as caught:
            registrar.apply(prepared, approval)
        assert caught.value.code is ReasonCode.APPROVAL_INVALID
        assert not fixture.config_path.exists()


@pytest.mark.parametrize("tamper", ["issuer-reference", "pre-window-time"])
def test_fixture_approval_is_bound_to_exact_active_issuance(
    tamper: str, tmp_path: Path
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        prepared = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )
        approval = fixture_approval(prepared)
        assert fixture.context.writer_window is not None
        if tamper == "issuer-reference":
            forged = replace(approval, issuer_reference="forged-fixture-reference")
        else:
            forged = replace(
                approval,
                issued_at=fixture.context.writer_window.acquired_at
                - timedelta(seconds=1),
            )
        with pytest.raises(RegistrarError) as caught:
            registrar.apply(prepared, forged)
        assert caught.value.code is ReasonCode.APPROVAL_INVALID
        assert not fixture.config_path.exists()


def test_fixture_approval_factory_rejects_foreign_issuer_reference(
    tmp_path: Path,
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        prepared = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )
        with pytest.raises(RegistrarError) as caught:
            fixture_approval(prepared, issuer_reference="foreign-reference")
        assert caught.value.code is ReasonCode.APPROVAL_INVALID
        assert not fixture.config_path.exists()


def test_apply_persists_the_exact_under_lock_approval_validation_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        prepared = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )
        issued = fixture_approval(prepared).issued_at
        approval = replace(
            fixture_approval(prepared, now=issued),
            expires_at=issued + timedelta(seconds=1),
        )
        calls = 0

        def advancing_time():
            nonlocal calls
            calls += 1
            return issued + timedelta(seconds=0.5 if calls <= 4 else 1.5)

        with monkeypatch.context() as patch:
            patch.setattr(registrar_transactions, "utc_now", advancing_time)
            assert registrar.apply(prepared, approval).outcome is Outcome.APPLIED
        journal = json.loads(
            StateStore(fixture.context)
            .journal_path(prepared.operation_id)
            .read_bytes()
        )
        assert journal["approval_validated_at"] == isoformat(
            issued + timedelta(seconds=0.5)
        )
        assert registrar.preview(
            fixture.config_path, definition, context=fixture.context
        ).ready


def test_expiry_after_lock_acquisition_refuses_before_journal_or_config_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        prepared = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )
        issued = fixture_approval(prepared).issued_at
        approval = replace(
            fixture_approval(prepared, now=issued),
            expires_at=issued + timedelta(seconds=1),
        )
        under_lock = False
        original_lock = StateStore.lock

        @contextmanager
        def advancing_lock(store, target_id):
            nonlocal under_lock
            with original_lock(store, target_id):
                under_lock = True
                yield

        def observed_time():
            return issued + timedelta(seconds=1.5 if under_lock else 0.5)

        before = {
            str(path.relative_to(fixture.root)): path.read_bytes()
            for path in fixture.root.rglob("*")
            if path.is_file()
        }
        with monkeypatch.context() as patch:
            patch.setattr(StateStore, "lock", advancing_lock)
            patch.setattr(registrar_transactions, "utc_now", observed_time)
            with pytest.raises(RegistrarError) as caught:
                registrar.apply(prepared, approval)
        assert caught.value.code is ReasonCode.APPROVAL_INVALID
        after = {
            str(path.relative_to(fixture.root)): path.read_bytes()
            for path in fixture.root.rglob("*")
            if path.is_file()
        }
        assert after == before
        assert not fixture.config_path.exists()


def test_changed_or_missing_prepared_record_never_writes(tmp_path: Path) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        prepared = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )
        approval = fixture_approval(prepared)
        record = fixture.state_directory / f"prepared-{prepared.record_id}.json"
        record.write_text("{}\n")
        record.chmod(0o600)
        with pytest.raises(RegistrarError) as caught:
            registrar.apply(prepared, approval)
        assert caught.value.code is ReasonCode.STATE_INVALID
        assert not fixture.config_path.exists()
        record.unlink()
        with pytest.raises(RegistrarError) as caught:
            registrar.apply(prepared, approval)
        assert caught.value.code is ReasonCode.PREPARED_RECORD_REQUIRED


@pytest.mark.parametrize("field", ["action_digest", "audience", "expires_at"])
def test_tampered_prepared_facade_never_writes(
    field: str, tmp_path: Path
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        prepared = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )
        if field == "action_digest":
            forged = replace(prepared, action_digest="f" * 64)
        elif field == "audience":
            forged = replace(
                prepared,
                audience=replace(
                    prepared.audience,
                    host="forged-host",
                    target_id="0" * 64,
                ),
            )
        else:
            forged = replace(
                prepared, expires_at=prepared.expires_at + timedelta(minutes=5)
            )
        with pytest.raises(RegistrarError) as caught:
            registrar.apply(forged, fixture_approval(forged))
        assert caught.value.code is ReasonCode.STATE_INVALID
        assert not fixture.config_path.exists()


@pytest.mark.parametrize("mismatch", ["host", "surface", "scope", "origin"])
def test_auth_binding_is_bound_to_exact_context_and_origin(
    mismatch: str, tmp_path: Path
) -> None:
    registrar = CursorRegistrar()
    definition = RegistrationDefinition.streamable_http(
        SourceIdentity(
            source_owner="KleinPerkins/kp-mcp",
            connection_id="kp-mcp:auth-fixture",
            source_revision="9" * 40,
            native_name="auth-fixture",
        ),
        url="https://fixture.invalid/mcp",
    )
    values = {
        "host": "fixture",
        "surface": registrar.SURFACE,
        "scope": "user",
        "target_origin_digest": definition.target_origin_digest,
    }
    if mismatch == "origin":
        values["target_origin_digest"] = "0" * 64
    else:
        values[mismatch] = f"wrong-{mismatch}"
    binding = AuthBinding(
        binding_id="fixture-auth-binding",
        kind=AuthKind.ENVIRONMENT_REFERENCE,
        allowed_native_fields=("/headers/Authorization",),
        environment_variable="FIXTURE_TOKEN",
        **values,
    )
    if mismatch in {"host", "surface", "scope"}:
        with pytest.raises(RegistrarError) as caught:
            with fixture_context(
                registrar,
                definition,
                fixture_root=tmp_path,
                auth_binding=binding,
            ):
                pass
    else:
        with fixture_context(
            registrar,
            definition,
            fixture_root=tmp_path,
            auth_binding=binding,
        ) as fixture:
            with pytest.raises(RegistrarError) as caught:
                registrar.preview(
                    fixture.config_path, definition, context=fixture.context
                )
            assert not fixture.config_path.exists()
    assert caught.value.code is ReasonCode.AUTH_BINDING_CONFLICT


def test_valid_reference_only_auth_writes_reference_not_secret(
    tmp_path: Path,
) -> None:
    registrar = CursorRegistrar()
    definition = RegistrationDefinition.streamable_http(
        SourceIdentity(
            source_owner="KleinPerkins/kp-mcp",
            connection_id="kp-mcp:auth-fixture",
            source_revision="8" * 40,
            native_name="auth-fixture",
        ),
        url="https://fixture.invalid/mcp",
    )
    binding = AuthBinding(
        binding_id="fixture-auth-binding",
        kind=AuthKind.ENVIRONMENT_REFERENCE,
        host="fixture",
        surface=registrar.SURFACE,
        scope="user",
        target_origin_digest=definition.target_origin_digest,
        allowed_native_fields=("/headers/Authorization",),
        environment_variable="FIXTURE_TOKEN",
    )
    with fixture_context(
        registrar,
        definition,
        fixture_root=tmp_path,
        auth_binding=binding,
    ) as fixture:
        prepared = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )
        registrar.apply(prepared, fixture_approval(prepared))
        written = fixture.config_path.read_text()
        assert "${env:FIXTURE_TOKEN}" in written
        assert SECRET not in written


@pytest.mark.parametrize("include_auth_leaf", [False, True])
def test_migration_evidence_binds_exact_source_and_auth_leaf_union(
    include_auth_leaf: bool, tmp_path: Path
) -> None:
    registrar = CursorRegistrar()
    definition = RegistrationDefinition.streamable_http(
        SourceIdentity(
            source_owner="KleinPerkins/kp-mcp",
            connection_id="kp-mcp:migration-auth-fixture",
            source_revision="7" * 40,
            native_name="migration-auth-fixture",
        ),
        url="https://fixture.invalid/mcp",
    )
    binding = AuthBinding(
        binding_id="fixture-migration-auth-binding",
        kind=AuthKind.ENVIRONMENT_REFERENCE,
        host="fixture",
        surface=registrar.SURFACE,
        scope="user",
        target_origin_digest=definition.target_origin_digest,
        allowed_native_fields=("/headers/Authorization",),
        environment_variable="FIXTURE_TOKEN",
    )
    with fixture_context(
        registrar,
        definition,
        fixture_root=tmp_path,
        auth_binding=binding,
    ) as fixture:
        fixture.config_path.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        definition.native_name: {
                            "url": definition.transport.url,
                            "headers": {
                                "Authorization": "${env:FIXTURE_TOKEN}"
                            },
                        }
                    }
                }
            )
        )
        before = fixture.config_path.read_bytes()
        target = inspect_target(fixture.config_path)
        leaves = [("/url", digest_value(definition.transport.url))]
        if include_auth_leaf:
            leaves.append(
                (
                    "/headers/Authorization",
                    digest_value("${env:FIXTURE_TOKEN}"),
                )
            )
        evidence = MigrationEvidence(
            evidence_id="fixture-auth-migration",
            source_owner=definition.source_owner,
            connection_id=definition.connection_id,
            source_revision=definition.source_revision,
            host=fixture.context.host,
            scope=fixture.context.scope,
            native_name=definition.native_name,
            target_id=target.target_id,
            whole_file_digest=digest_bytes(before),
            owned_leaf_digests=tuple(leaves),
            provenance_reference="fixture-migration-evidence",
            retiring_writer_handoff="retired-fixture-writer",
        )
        context = replace(fixture.context, migration_evidence=evidence)
        preview = registrar.preview(
            fixture.config_path, definition, context=context
        )
        if not include_auth_leaf:
            assert ReasonCode.OWNERSHIP_UNKNOWN in preview.conflicts
            with pytest.raises(RegistrarError):
                registrar.prepare(preview)
            assert fixture.config_path.read_bytes() == before
            return
        assert preview.action.value == "adopt"
        assert preview.ready
        assert preview.config_changed is False
        prepared = registrar.prepare(preview)
        result = registrar.apply(prepared, fixture_approval(prepared))
        assert result.outcome is Outcome.APPLIED
        assert result.config_changed is False
        assert fixture.config_path.read_bytes() == before


def test_unqualified_or_expired_writer_window_cannot_mutate(
    tmp_path: Path,
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    context = registrar.read_only_context(
        definition,
        config_path=tmp_path / "mcp.json",
        state_directory=state,
        host="fixture-host",
        surface=registrar.SURFACE,
        build="cursor-source-v1",
    )
    preview = registrar.preview(context.config_path, definition, context=context)
    with pytest.raises(RegistrarError) as caught:
        registrar.prepare(preview)
    assert caught.value.code is ReasonCode.CONCURRENCY_UNQUALIFIED
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        assert fixture.context.writer_window is not None
        expired_window = replace(
            fixture.context.writer_window,
            acquired_at=fixture.context.writer_window.acquired_at
            - timedelta(minutes=20),
            expires_at=fixture.context.writer_window.acquired_at
            - timedelta(minutes=10),
        )
        expired = replace(fixture.context, writer_window=expired_window)
        preview = registrar.preview(
            fixture.config_path, definition, context=expired
        )
        with pytest.raises(RegistrarError) as caught:
            registrar.prepare(preview)
        assert caught.value.code in {
            ReasonCode.CONCURRENCY_UNQUALIFIED,
            ReasonCode.STALE_PREVIEW,
        }


@pytest.mark.parametrize(
    "context_changes,window_changes",
    [
        ({"host": "claimed-live-host", "build": "cursor-source-v1"}, {}),
        ({"scope": "project"}, {}),
        ({}, {"host": "claimed-live-host"}),
        ({}, {"build": "cursor-source-v1"}),
        ({}, {"issuer_source_revision": "f" * 40}),
    ],
)
def test_fixture_writer_evidence_cannot_be_relabelled(
    context_changes: dict[str, str],
    window_changes: dict[str, str],
    tmp_path: Path,
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        assert fixture.context.writer_window is not None
        window = replace(fixture.context.writer_window, **window_changes)
        context = replace(
            fixture.context,
            writer_window=window,
            **context_changes,
        )
        preview = registrar.preview(
            fixture.config_path, definition, context=context
        )
        with pytest.raises(RegistrarError) as caught:
            registrar.prepare(preview)
        assert caught.value.code is ReasonCode.CONCURRENCY_UNQUALIFIED
        assert not fixture.config_path.exists()


@pytest.mark.parametrize(
    "corruption",
    [
        "missing-source-paths",
        "nonmapping-source-paths",
        "unknown-source-field",
        "invalid-pointer",
        "invalid-digest",
        "partial-auth-identity",
        "forged-operation",
    ],
)
def test_malformed_receipt_never_reestablishes_ownership(
    corruption: str, tmp_path: Path
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        prepared = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )
        approval = fixture_approval(prepared)
        registrar.apply(prepared, approval)
        config_before = fixture.config_path.read_bytes()
        receipt_path = next(fixture.state_directory.glob("receipt-*.json"))
        receipt = json.loads(receipt_path.read_bytes())
        if corruption == "missing-source-paths":
            receipt["source_projection"]["paths"] = {}
        elif corruption == "nonmapping-source-paths":
            receipt["source_projection"]["paths"] = []
        elif corruption == "unknown-source-field":
            receipt["source_projection"]["unknown"] = True
        elif corruption == "invalid-pointer":
            receipt["source_projection"]["paths"] = {"/bad~2path": "0" * 64}
        elif corruption == "invalid-digest":
            path = next(iter(receipt["source_projection"]["paths"]))
            receipt["source_projection"]["paths"][path] = "not-a-digest"
        elif corruption == "partial-auth-identity":
            receipt["auth_projection"]["owner"] = "forged-owner"
        else:
            receipt["operation_id"] = "forged-operation"
        receipt_path.write_text(json.dumps(receipt))

        for operation in (
            lambda: registrar.preview(
                fixture.config_path, definition, context=fixture.context
            ),
            lambda: registrar.inspect_registration(
                fixture.config_path, context=fixture.context
            ),
            lambda: registrar.apply(prepared, approval),
        ):
            with pytest.raises(RegistrarError) as caught:
                operation()
            assert caught.value.code in {
                ReasonCode.STATE_INVALID,
                ReasonCode.PREIMAGE_CHANGED,
            }
            assert str(fixture.config_path) not in str(caught.value)
            assert fixture.config_path.read_bytes() == config_before


def test_permission_failure_is_bounded_without_private_path_egress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        original_lstat = Path.lstat

        def deny_config(path: Path):
            if path == fixture.config_path:
                raise PermissionError(f"private path: {path}")
            return original_lstat(path)

        monkeypatch.setattr(Path, "lstat", deny_config)
        with pytest.raises(RegistrarError) as caught:
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        assert caught.value.code is ReasonCode.PERMISSION_DENIED
        assert str(fixture.config_path) not in str(caught.value)


def test_fixture_release_failure_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    original_rmtree = registrar_writer_window.shutil.rmtree
    fixture_root: Path | None = None

    def fail_release(_path: Path) -> None:
        raise OSError("synthetic release failure with private path")

    monkeypatch.setattr(registrar_writer_window.shutil, "rmtree", fail_release)
    try:
        with pytest.raises(RegistrarError) as caught:
            with fixture_context(
                registrar, definition, fixture_root=tmp_path
            ) as fixture:
                fixture_root = fixture.root
        assert caught.value.code is ReasonCode.WRITER_RELEASE_FAILED
        assert "synthetic" not in str(caught.value)
    finally:
        if fixture_root is not None and fixture_root.exists():
            original_rmtree(fixture_root)
