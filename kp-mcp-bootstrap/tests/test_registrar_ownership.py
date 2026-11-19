"""Per-leaf ownership, adoption, switch, and withdrawal tests."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from kp_mcp_bootstrap.registrars import (
    AuthBinding,
    AuthKind,
    CodexRegistrar,
    CursorRegistrar,
    MigrationEvidence,
    Outcome,
    ReasonCode,
    RegistrarError,
    RegistrationDefinition,
    SourceIdentity,
    fixture_approval,
    fixture_context,
    operation_ref,
)
from kp_mcp_bootstrap.registrars.contracts import (
    ABSENT_DIGEST,
    digest_bytes,
    digest_value,
)
from kp_mcp_bootstrap.registrars.state import StateStore, inspect_target
from kp_mcp_bootstrap.registrars.ownership import reconcile_entry


def _identity(revision: str = "e" * 40) -> SourceIdentity:
    return SourceIdentity(
        source_owner="KleinPerkins/kp-mcp",
        connection_id="kp-mcp:ownership-fixture",
        source_revision=revision,
        native_name="ownership-fixture",
    )


def _stdio(
    revision: str = "e" * 40, *, env: dict[str, str] | None = None
) -> RegistrationDefinition:
    return RegistrationDefinition.stdio(
        _identity(revision),
        command="/opt/fixtures/ownership",
        args=("mcp",),
        env=env,
    )


def _apply(registrar, fixture, definition):
    prepared = registrar.prepare(
        registrar.preview(
            fixture.config_path, definition, context=fixture.context
        )
    )
    return registrar.apply(prepared, fixture_approval(prepared))


def test_unknown_equal_same_name_requires_explicit_adoption(tmp_path: Path) -> None:
    registrar = CursorRegistrar()
    definition = _stdio()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        fixture.config_path.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        definition.native_name: {
                            "command": "/opt/fixtures/ownership",
                            "args": ["mcp"],
                        }
                    }
                }
            )
        )
        before = fixture.config_path.read_bytes()
        unknown = registrar.preview(
            fixture.config_path, definition, context=fixture.context
        )
        assert unknown.conflicts == (ReasonCode.OWNERSHIP_UNKNOWN,)
        binding = inspect_target(fixture.config_path)
        source = {"/command": "/opt/fixtures/ownership", "/args": ["mcp"]}
        evidence = MigrationEvidence(
            evidence_id="fixture-handoff",
            source_owner=definition.source_owner,
            connection_id=definition.connection_id,
            source_revision=definition.source_revision,
            host=fixture.context.host,
            scope=fixture.context.scope,
            native_name=definition.native_name,
            target_id=binding.target_id,
            whole_file_digest=digest_bytes(before),
            owned_leaf_digests=tuple(
                (path, digest_value(value)) for path, value in source.items()
            ),
            provenance_reference="fixture-evidence",
            retiring_writer_handoff="retired-fixture-writer",
        )
        adopted_context = replace(
            fixture.context, migration_evidence=evidence
        )
        adopted = registrar.preview(
            fixture.config_path, definition, context=adopted_context
        )
        assert adopted.action.value == "adopt"
        assert not adopted.config_changed and adopted.state_changed
        prepared = registrar.prepare(adopted)
        result = registrar.apply(prepared, fixture_approval(prepared))
        assert result.outcome is Outcome.APPLIED
        assert not result.config_changed and result.state_changed
        assert fixture.config_path.read_bytes() == before


def test_per_key_env_merge_preserves_user_leaf_and_removes_owned_leaf(
    tmp_path: Path,
) -> None:
    registrar = CursorRegistrar()
    first = _stdio(env={"OWNED_A": "one", "OWNED_B": "two"})
    with fixture_context(registrar, first, fixture_root=tmp_path) as fixture:
        _apply(registrar, fixture, first)
        data = json.loads(fixture.config_path.read_text())
        data["mcpServers"][first.native_name]["env"]["USER_KEEP"] = "preserved"
        fixture.config_path.write_text(json.dumps(data))
        second = _stdio("f" * 40, env={"OWNED_A": "updated"})
        second_context = replace(
            fixture.context,
            source_revision=second.source_revision,
            definition_digest=second.digest,
        )
        preview = registrar.preview(
            fixture.config_path, second, context=second_context
        )
        assert preview.ready
        prepared = registrar.prepare(preview)
        registrar.apply(prepared, fixture_approval(prepared))
        env = json.loads(fixture.config_path.read_text())["mcpServers"][
            first.native_name
        ]["env"]
        assert env == {"OWNED_A": "updated", "USER_KEEP": "preserved"}


def test_multi_header_auth_merge_removes_only_withdrawn_owned_leaf(
    tmp_path: Path,
) -> None:
    registrar = CodexRegistrar()
    first = RegistrationDefinition.streamable_http(
        _identity("7" * 40), url="https://example.invalid/mcp"
    )
    first_binding = AuthBinding(
        binding_id="ownership-multi-header-first",
        kind=AuthKind.ENVIRONMENT_REFERENCE,
        host="fixture",
        surface=registrar.SURFACE,
        scope="user",
        target_origin_digest=first.target_origin_digest,
        allowed_native_fields=(
            "/env_http_headers/X-First",
            "/env_http_headers/X-Second",
        ),
        environment_variable="FIXTURE_TOKEN",
    )
    with fixture_context(
        registrar,
        first,
        fixture_root=tmp_path,
        auth_binding=first_binding,
    ) as fixture:
        _apply(registrar, fixture, first)
        second = RegistrationDefinition.streamable_http(
            _identity("8" * 40), url="https://example.invalid/mcp"
        )
        second_binding = AuthBinding(
            binding_id="ownership-multi-header-second",
            kind=AuthKind.ENVIRONMENT_REFERENCE,
            host=fixture.context.host,
            surface=fixture.context.surface,
            scope=fixture.context.scope,
            target_origin_digest=second.target_origin_digest,
            allowed_native_fields=("/env_http_headers/X-First",),
            environment_variable="FIXTURE_TOKEN",
        )
        context = replace(
            fixture.context,
            source_revision=second.source_revision,
            definition_digest=second.digest,
            auth_binding=second_binding,
        )
        prepared = registrar.prepare(
            registrar.preview(fixture.config_path, second, context=context)
        )
        registrar.apply(prepared, fixture_approval(prepared))
        written = registrar._parse_bytes(fixture.config_path.read_bytes())[
            "mcp_servers"
        ][first.native_name]["env_http_headers"]
        assert dict(written) == {"X-First": "FIXTURE_TOKEN"}


def test_source_and_auth_projection_overlap_fails_closed() -> None:
    current: dict[str, object] = {}
    result = reconcile_entry(
        current,
        {"/headers/Authorization": "source-value"},
        {"/headers/Authorization": "auth-value"},
        None,
        adoption=False,
        incompatible_paths=frozenset(),
    )
    assert result.conflicts == (ReasonCode.AUTH_BINDING_CONFLICT,)
    assert current == {}


def test_receipt_previous_digest_is_bound_to_exact_preimage(
    tmp_path: Path,
) -> None:
    registrar = CursorRegistrar()
    definition = _stdio()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        _apply(registrar, fixture, definition)
        receipt_path = StateStore(fixture.context).receipt_path()
        receipt = json.loads(receipt_path.read_bytes())
        assert receipt["previous_receipt_digest"] == ABSENT_DIGEST
        receipt["previous_receipt_digest"] = "0" * 64
        receipt_path.write_bytes(
            json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
            + b"\n"
        )
        receipt_path.chmod(0o600)
        before = receipt_path.read_bytes()
        with pytest.raises(RegistrarError) as caught:
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        assert caught.value.code is ReasonCode.STATE_INVALID
        assert receipt_path.read_bytes() == before


def test_equal_unowned_leaf_is_not_silently_added_to_existing_receipt(
    tmp_path: Path,
) -> None:
    registrar = CursorRegistrar()
    first = _stdio(env={"OWNED": "one"})
    with fixture_context(registrar, first, fixture_root=tmp_path) as fixture:
        _apply(registrar, fixture, first)
        data = json.loads(fixture.config_path.read_text())
        data["mcpServers"][first.native_name]["env"]["USER_OWNED"] = "same"
        fixture.config_path.write_text(json.dumps(data))
        before = fixture.config_path.read_bytes()
        second = _stdio(
            "a" * 40,
            env={"OWNED": "one", "USER_OWNED": "same"},
        )
        context = replace(
            fixture.context,
            source_revision=second.source_revision,
            definition_digest=second.digest,
        )
        preview = registrar.preview(
            fixture.config_path, second, context=context
        )
        assert ReasonCode.OWNER_CONFLICT in preview.conflicts
        with pytest.raises(RegistrarError):
            registrar.prepare(preview)
        assert fixture.config_path.read_bytes() == before


def test_owned_drift_blocks_and_preserves_bytes(tmp_path: Path) -> None:
    registrar = CursorRegistrar()
    definition = _stdio()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        _apply(registrar, fixture, definition)
        data = json.loads(fixture.config_path.read_text())
        data["mcpServers"][definition.native_name]["command"] = "/user/change"
        fixture.config_path.write_text(json.dumps(data))
        before = fixture.config_path.read_bytes()
        preview = registrar.preview(
            fixture.config_path, definition, context=fixture.context
        )
        assert ReasonCode.OWNED_FIELD_DRIFT in preview.conflicts
        with pytest.raises(RegistrarError):
            registrar.prepare(preview)
        assert fixture.config_path.read_bytes() == before


def test_update_preserves_disabled_approval_timeout_and_unknown_fields(
    tmp_path: Path,
) -> None:
    registrar = CursorRegistrar()
    first = _stdio()
    with fixture_context(registrar, first, fixture_root=tmp_path) as fixture:
        _apply(registrar, fixture, first)
        data = json.loads(fixture.config_path.read_text())
        entry = data["mcpServers"][first.native_name]
        preserved = {
            "disabled": True,
            "approval": "manual",
            "timeout": 45,
            "unknown_host_field": {"keep": "exact"},
        }
        entry.update(preserved)
        fixture.config_path.write_text(json.dumps(data))
        updated = RegistrationDefinition.stdio(
            _identity("3" * 40),
            command="/opt/fixtures/ownership-updated",
            args=("mcp",),
        )
        context = replace(
            fixture.context,
            source_revision=updated.source_revision,
            definition_digest=updated.digest,
        )
        prepared = registrar.prepare(
            registrar.preview(
                fixture.config_path, updated, context=context
            )
        )
        registrar.apply(prepared, fixture_approval(prepared))
        written = json.loads(fixture.config_path.read_text())["mcpServers"][
            first.native_name
        ]
        assert written["command"] == "/opt/fixtures/ownership-updated"
        for key, value in preserved.items():
            assert written[key] == value


def test_case_insensitive_header_collision_refuses_without_change(
    tmp_path: Path,
) -> None:
    registrar = CursorRegistrar()
    remote = RegistrationDefinition.streamable_http(
        _identity("4" * 40), url="https://example.invalid/mcp"
    )
    binding = AuthBinding(
        binding_id="ownership-header-auth",
        kind=AuthKind.ENVIRONMENT_REFERENCE,
        host="fixture",
        surface=registrar.SURFACE,
        scope="user",
        target_origin_digest=remote.target_origin_digest,
        allowed_native_fields=("/headers/Authorization",),
        environment_variable="FIXTURE_TOKEN",
    )
    with fixture_context(
        registrar, remote, fixture_root=tmp_path, auth_binding=binding
    ) as fixture:
        _apply(registrar, fixture, remote)
        data = json.loads(fixture.config_path.read_text())
        data["mcpServers"][remote.native_name]["headers"][
            "authorization"
        ] = "different-reference"
        fixture.config_path.write_text(json.dumps(data))
        before = fixture.config_path.read_bytes()
        preview = registrar.preview(
            fixture.config_path, remote, context=fixture.context
        )
        assert ReasonCode.AUTH_BINDING_CONFLICT in preview.conflicts
        with pytest.raises(RegistrarError):
            registrar.prepare(preview)
        assert fixture.config_path.read_bytes() == before


@pytest.mark.parametrize("direction", ["stdio-to-http", "http-to-stdio"])
def test_transport_switch_refuses_incompatible_unowned_policy(
    direction: str, tmp_path: Path
) -> None:
    registrar = CursorRegistrar()
    stdio = _stdio("5" * 40, env={"OWNED": "one"})
    remote = RegistrationDefinition.streamable_http(
        _identity("6" * 40), url="https://example.invalid/mcp"
    )
    remote_none = AuthBinding.none(
        binding_id="ownership-switch-http-none",
        host="fixture",
        surface=registrar.SURFACE,
        scope="user",
        target_origin_digest=remote.target_origin_digest,
    )
    initial = stdio if direction == "stdio-to-http" else remote
    initial_auth = None if initial is stdio else remote_none
    with fixture_context(
        registrar,
        initial,
        fixture_root=tmp_path,
        auth_binding=initial_auth,
    ) as fixture:
        _apply(registrar, fixture, initial)
        data = json.loads(fixture.config_path.read_text())
        entry = data["mcpServers"][initial.native_name]
        if direction == "stdio-to-http":
            entry.setdefault("env", {})["USER_POLICY"] = "preserve"
            desired = remote
            desired_auth = remote_none
        else:
            entry.setdefault("headers", {})["X-User-Policy"] = "preserve"
            desired = stdio
            desired_auth = AuthBinding.none(
                binding_id="ownership-switch-stdio-none",
                host="fixture",
                surface=registrar.SURFACE,
                scope="user",
                target_origin_digest=stdio.target_origin_digest,
            )
        fixture.config_path.write_text(json.dumps(data))
        before = fixture.config_path.read_bytes()
        context = replace(
            fixture.context,
            source_revision=desired.source_revision,
            definition_digest=desired.digest,
            auth_binding=desired_auth,
        )
        preview = registrar.preview(
            fixture.config_path, desired, context=context
        )
        assert ReasonCode.POLICY_CONFLICT in preview.conflicts
        with pytest.raises(RegistrarError):
            registrar.prepare(preview)
        assert fixture.config_path.read_bytes() == before


def test_stdio_http_switch_removes_only_prior_owned_fields(tmp_path: Path) -> None:
    registrar = CursorRegistrar()
    stdio = _stdio(env={"OWNED": "one"})
    with fixture_context(registrar, stdio, fixture_root=tmp_path) as fixture:
        _apply(registrar, fixture, stdio)
        remote = RegistrationDefinition.streamable_http(
            _identity("1" * 40), url="https://example.invalid/mcp"
        )
        remote_context = replace(
            fixture.context,
            source_revision=remote.source_revision,
            definition_digest=remote.digest,
            auth_binding=AuthBinding.none(
                binding_id="ownership-http-no-auth",
                host=fixture.context.host,
                surface=fixture.context.surface,
                scope=fixture.context.scope,
                target_origin_digest=remote.target_origin_digest,
            ),
        )
        preview = registrar.preview(
            fixture.config_path, remote, context=remote_context
        )
        assert preview.ready
        prepared = registrar.prepare(preview)
        registrar.apply(prepared, fixture_approval(prepared))
        entry = json.loads(fixture.config_path.read_text())["mcpServers"][
            stdio.native_name
        ]
        assert entry == {"url": "https://example.invalid/mcp"}
        removal = registrar.prepare(
            registrar.preview_unregister(
                fixture.config_path, context=remote_context
            )
        )
        registrar.apply(removal, fixture_approval(removal))
        assert stdio.native_name not in json.loads(
            fixture.config_path.read_text()
        )["mcpServers"]


def test_unregister_refuses_preserved_policy_then_removes_fully_owned_entry(
    tmp_path: Path,
) -> None:
    registrar = CursorRegistrar()
    definition = _stdio()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        _apply(registrar, fixture, definition)
        data = json.loads(fixture.config_path.read_text())
        data["mcpServers"][definition.native_name]["disabled"] = True
        fixture.config_path.write_text(json.dumps(data))
        blocked = registrar.preview_unregister(
            fixture.config_path, context=fixture.context
        )
        assert blocked.conflicts == (ReasonCode.REMOVAL_CONFLICT,)
        data["mcpServers"][definition.native_name].pop("disabled")
        fixture.config_path.write_text(json.dumps(data))
        removal = registrar.prepare(
            registrar.preview_unregister(
                fixture.config_path, context=fixture.context
            )
        )
        result = registrar.apply(removal, fixture_approval(removal))
        assert result.outcome is Outcome.APPLIED
        assert definition.native_name not in json.loads(
            fixture.config_path.read_text()
        )["mcpServers"]


@pytest.mark.parametrize("ancestor", [None, "scalar", ["list"]])
def test_adoption_never_overwrites_explicit_non_mapping_ancestor(
    ancestor: object, tmp_path: Path
) -> None:
    registrar = CursorRegistrar()
    definition = _stdio(env={"FOO": "bar"})
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        fixture.config_path.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        definition.native_name: {
                            "command": "/opt/fixtures/ownership",
                            "args": ["mcp"],
                            "env": ancestor,
                        }
                    }
                }
            )
        )
        before = fixture.config_path.read_bytes()
        binding = inspect_target(fixture.config_path)
        evidence = MigrationEvidence(
            evidence_id="fixture-null-ancestor-handoff",
            source_owner=definition.source_owner,
            connection_id=definition.connection_id,
            source_revision=definition.source_revision,
            host=fixture.context.host,
            scope=fixture.context.scope,
            native_name=definition.native_name,
            target_id=binding.target_id,
            whole_file_digest=digest_bytes(before),
            owned_leaf_digests=(
                ("/args", digest_value(["mcp"])),
                ("/command", digest_value("/opt/fixtures/ownership")),
                ("/env/FOO", ABSENT_DIGEST),
            ),
            provenance_reference="fixture-evidence",
            retiring_writer_handoff="retired-fixture-writer",
        )
        context = replace(fixture.context, migration_evidence=evidence)
        preview = registrar.preview(
            fixture.config_path, definition, context=context
        )
        assert preview.action.value == "adopt"
        assert ReasonCode.OWNER_CONFLICT in preview.conflicts
        with pytest.raises(RegistrarError):
            registrar.prepare(preview)
        assert fixture.config_path.read_bytes() == before


def test_adoption_distinguishes_empty_mapping_from_non_mapping_ancestor(
    tmp_path: Path,
) -> None:
    registrar = CursorRegistrar()
    definition = _stdio(env={"FOO": "bar"})
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        fixture.config_path.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        definition.native_name: {
                            "command": "/opt/fixtures/ownership",
                            "args": ["mcp"],
                            "env": {},
                        }
                    }
                }
            )
        )
        before = fixture.config_path.read_bytes()
        binding = inspect_target(fixture.config_path)
        evidence = MigrationEvidence(
            evidence_id="fixture-empty-map-handoff",
            source_owner=definition.source_owner,
            connection_id=definition.connection_id,
            source_revision=definition.source_revision,
            host=fixture.context.host,
            scope=fixture.context.scope,
            native_name=definition.native_name,
            target_id=binding.target_id,
            whole_file_digest=digest_bytes(before),
            owned_leaf_digests=(
                ("/args", digest_value(["mcp"])),
                ("/command", digest_value("/opt/fixtures/ownership")),
                ("/env/FOO", ABSENT_DIGEST),
            ),
            provenance_reference="fixture-evidence",
            retiring_writer_handoff="retired-fixture-writer",
        )
        context = replace(fixture.context, migration_evidence=evidence)
        preview = registrar.preview(
            fixture.config_path, definition, context=context
        )
        assert preview.ready
        prepared = registrar.prepare(preview)
        registrar.apply(prepared, fixture_approval(prepared))
        entry = json.loads(fixture.config_path.read_text())["mcpServers"][
            definition.native_name
        ]
        assert entry["env"] == {"FOO": "bar"}
        remote = RegistrationDefinition.streamable_http(
            _identity("9" * 40), url="https://example.invalid/mcp"
        )
        context = replace(
            fixture.context,
            source_revision=remote.source_revision,
            definition_digest=remote.digest,
            migration_evidence=None,
            auth_binding=AuthBinding.none(
                binding_id="preserve-user-empty-env",
                host=fixture.context.host,
                surface=fixture.context.surface,
                scope=fixture.context.scope,
                target_origin_digest=remote.target_origin_digest,
            ),
        )
        prepared = registrar.prepare(
            registrar.preview(fixture.config_path, remote, context=context)
        )
        registrar.apply(prepared, fixture_approval(prepared))
        switched = json.loads(fixture.config_path.read_text())["mcpServers"][
            definition.native_name
        ]
        assert switched["env"] == {}
        assert registrar.preview_unregister(
            fixture.config_path, context=context
        ).conflicts == (ReasonCode.REMOVAL_CONFLICT,)


def test_owned_auth_removal_requires_explicit_target_bound_none(
    tmp_path: Path,
) -> None:
    registrar = CursorRegistrar()
    identity = _identity()
    remote = RegistrationDefinition.streamable_http(
        identity, url="https://example.invalid/mcp"
    )
    remote_binding = AuthBinding(
        binding_id="ownership-http-auth",
        kind=AuthKind.ENVIRONMENT_REFERENCE,
        host="fixture",
        surface=registrar.SURFACE,
        scope="user",
        target_origin_digest=remote.target_origin_digest,
        allowed_native_fields=("/headers/Authorization",),
        environment_variable="FIXTURE_TOKEN",
    )
    with fixture_context(
        registrar,
        remote,
        fixture_root=tmp_path,
        auth_binding=remote_binding,
    ) as fixture:
        _apply(registrar, fixture, remote)
        before = fixture.config_path.read_bytes()
        local = _stdio("2" * 40)
        omitted = replace(
            fixture.context,
            source_revision=local.source_revision,
            definition_digest=local.digest,
            auth_binding=None,
        )
        blocked = registrar.preview(
            fixture.config_path, local, context=omitted
        )
        assert ReasonCode.AUTH_BINDING_CONFLICT in blocked.conflicts
        assert fixture.config_path.read_bytes() == before
        explicit_none = replace(
            omitted,
            auth_binding=AuthBinding.none(
                binding_id="ownership-stdio-no-auth",
                host=omitted.host,
                surface=omitted.surface,
                scope=omitted.scope,
                target_origin_digest=local.target_origin_digest,
            ),
        )
        approved = registrar.preview(
            fixture.config_path, local, context=explicit_none
        )
        assert approved.ready
        prepared = registrar.prepare(approved)
        registrar.apply(prepared, fixture_approval(prepared))
        entry = json.loads(fixture.config_path.read_text())["mcpServers"][
            local.native_name
        ]
        assert entry == {
            "args": ["mcp"],
            "command": "/opt/fixtures/ownership",
        }
        removal = registrar.prepare(
            registrar.preview_unregister(
                fixture.config_path, context=explicit_none
            )
        )
        registrar.apply(removal, fixture_approval(removal))
        assert local.native_name not in json.loads(
            fixture.config_path.read_text()
        )["mcpServers"]


def _remote_auth_contract(
    registrar: CursorRegistrar,
) -> tuple[RegistrationDefinition, AuthBinding]:
    remote = RegistrationDefinition.streamable_http(
        _identity("a" * 40), url="https://example.invalid/mcp"
    )
    binding = AuthBinding(
        binding_id="ownership-removal-auth",
        kind=AuthKind.ENVIRONMENT_REFERENCE,
        host="fixture",
        surface=registrar.SURFACE,
        scope="user",
        target_origin_digest=remote.target_origin_digest,
        allowed_native_fields=("/headers/Authorization",),
        environment_variable="FIXTURE_TOKEN",
    )
    return remote, binding


def _auth_removal_context(fixture, remote, *, origin: str | None = None):
    return replace(
        fixture.context,
        auth_binding=AuthBinding.none(
            binding_id="ownership-explicit-auth-removal",
            host=fixture.context.host,
            surface=fixture.context.surface,
            scope=fixture.context.scope,
            target_origin_digest=origin or remote.target_origin_digest,
        ),
    )


def test_unregister_names_auth_removal_and_requires_explicit_none(
    tmp_path: Path,
) -> None:
    registrar = CursorRegistrar()
    remote, binding = _remote_auth_contract(registrar)
    with fixture_context(
        registrar, remote, fixture_root=tmp_path, auth_binding=binding
    ) as fixture:
        _apply(registrar, fixture, remote)
        omitted = replace(fixture.context, auth_binding=None)
        assert registrar.preview_unregister(
            fixture.config_path, context=omitted
        ).conflicts == (ReasonCode.AUTH_BINDING_CONFLICT,)
        wrong = _auth_removal_context(fixture, remote, origin="0" * 64)
        assert registrar.preview_unregister(
            fixture.config_path, context=wrong
        ).conflicts == (ReasonCode.AUTH_BINDING_CONFLICT,)
        explicit = _auth_removal_context(fixture, remote)
        preview = registrar.preview_unregister(
            fixture.config_path, context=explicit
        )
        assert preview.ready
        assert ("/headers/Authorization", "remove") in {
            (item.path, item.action) for item in preview.owned_leaf_actions
        }
        prepared = registrar.prepare(preview)
        registrar.apply(prepared, fixture_approval(prepared))
        assert remote.native_name not in json.loads(
            fixture.config_path.read_text()
        )["mcpServers"]


def test_receipt_only_auth_retirement_still_requires_explicit_none(
    tmp_path: Path,
) -> None:
    registrar = CursorRegistrar()
    remote, binding = _remote_auth_contract(registrar)
    with fixture_context(
        registrar, remote, fixture_root=tmp_path, auth_binding=binding
    ) as fixture:
        _apply(registrar, fixture, remote)
        fixture.config_path.write_text(json.dumps({"mcpServers": {}}))
        before = fixture.config_path.read_bytes()

        omitted = replace(fixture.context, auth_binding=None)
        blocked = registrar.preview_unregister(
            fixture.config_path, context=omitted
        )
        assert blocked.conflicts == (ReasonCode.AUTH_BINDING_CONFLICT,)
        assert fixture.config_path.read_bytes() == before

        explicit = _auth_removal_context(fixture, remote)
        approved = registrar.preview_unregister(
            fixture.config_path, context=explicit
        )
        assert approved.ready
        assert approved.config_changed is False
        assert approved.state_changed is True
        assert ("/headers/Authorization", "remove") in {
            (item.path, item.action) for item in approved.owned_leaf_actions
        }
        prepared = registrar.prepare(approved)
        result = registrar.apply(prepared, fixture_approval(prepared))
        assert result.outcome is Outcome.NO_CHANGE
        assert result.state_changed is True
        assert fixture.config_path.read_bytes() == before


@pytest.mark.parametrize("pending", [False, True])
def test_auth_register_rollback_requires_explicit_none_for_inverse_removal(
    pending: bool, tmp_path: Path
) -> None:
    registrar = CursorRegistrar()
    remote, binding = _remote_auth_contract(registrar)
    with fixture_context(
        registrar, remote, fixture_root=tmp_path, auth_binding=binding
    ) as fixture:
        original = registrar.prepare(
            registrar.preview(
                fixture.config_path, remote, context=fixture.context
            )
        )
        if pending:
            def interrupt(step: str) -> None:
                if step == "config_replaced":
                    raise RuntimeError("fixture interruption")

            registrar._fault = interrupt  # type: ignore[method-assign]
            assert registrar.apply(
                original, fixture_approval(original)
            ).outcome is Outcome.RECOVERY_REQUIRED
            registrar._fault = lambda _step: None  # type: ignore[method-assign]
        else:
            assert registrar.apply(
                original, fixture_approval(original)
            ).outcome is Outcome.APPLIED
        reference = operation_ref(original, pending=pending)
        omitted = replace(fixture.context, auth_binding=None)
        assert ReasonCode.AUTH_BINDING_CONFLICT in registrar.rollback(
            reference, context=omitted
        ).conflicts
        wrong = _auth_removal_context(fixture, remote, origin="0" * 64)
        assert ReasonCode.AUTH_BINDING_CONFLICT in registrar.rollback(
            reference, context=wrong
        ).conflicts
        explicit = _auth_removal_context(fixture, remote)
        preview = registrar.rollback(reference, context=explicit)
        assert preview.ready
        assert ("/headers/Authorization", "remove") in {
            (item.path, item.action) for item in preview.owned_leaf_actions
        }
        inverse = registrar.prepare(preview)
        result = registrar.apply(inverse, fixture_approval(inverse))
        assert result.outcome is Outcome.ROLLED_BACK
        assert not fixture.config_path.exists()


def test_unregister_rollback_requires_original_binding_to_restore_auth(
    tmp_path: Path,
) -> None:
    registrar = CursorRegistrar()
    remote, binding = _remote_auth_contract(registrar)
    with fixture_context(
        registrar, remote, fixture_root=tmp_path, auth_binding=binding
    ) as fixture:
        _apply(registrar, fixture, remote)
        removal_context = _auth_removal_context(fixture, remote)
        removal = registrar.prepare(
            registrar.preview_unregister(
                fixture.config_path, context=removal_context
            )
        )
        registrar.apply(removal, fixture_approval(removal))
        reference = operation_ref(removal)
        omitted = replace(fixture.context, auth_binding=None)
        assert ReasonCode.AUTH_BINDING_CONFLICT in registrar.rollback(
            reference, context=omitted
        ).conflicts
        wrong_binding = replace(
            binding,
            binding_id="wrong-restoration-binding",
            environment_variable="OTHER_TOKEN",
        )
        wrong = replace(fixture.context, auth_binding=wrong_binding)
        assert ReasonCode.AUTH_BINDING_CONFLICT in registrar.rollback(
            reference, context=wrong
        ).conflicts
        preview = registrar.rollback(reference, context=fixture.context)
        assert preview.ready
        assert ("/headers/Authorization", "add") in {
            (item.path, item.action) for item in preview.owned_leaf_actions
        }
        inverse = registrar.prepare(preview)
        registrar.apply(inverse, fixture_approval(inverse))
        restored = json.loads(fixture.config_path.read_text())["mcpServers"][
            remote.native_name
        ]
        assert restored["headers"]["Authorization"] == "${env:FIXTURE_TOKEN}"


def test_preexisting_user_empty_auth_map_survives_owned_leaf_withdrawal(
    tmp_path: Path,
) -> None:
    registrar = CursorRegistrar()
    remote, binding = _remote_auth_contract(registrar)
    with fixture_context(
        registrar, remote, fixture_root=tmp_path, auth_binding=binding
    ) as fixture:
        fixture.config_path.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        remote.native_name: {
                            "url": remote.transport.url,
                            "headers": {},
                        }
                    }
                }
            )
        )
        before = fixture.config_path.read_bytes()
        target = inspect_target(fixture.config_path)
        evidence = MigrationEvidence(
            evidence_id="fixture-empty-auth-map-handoff",
            source_owner=remote.source_owner,
            connection_id=remote.connection_id,
            source_revision=remote.source_revision,
            host=fixture.context.host,
            scope=fixture.context.scope,
            native_name=remote.native_name,
            target_id=target.target_id,
            whole_file_digest=digest_bytes(before),
            owned_leaf_digests=(
                ("/headers/Authorization", ABSENT_DIGEST),
                ("/url", digest_value(remote.transport.url)),
            ),
            provenance_reference="fixture-evidence",
            retiring_writer_handoff="retired-fixture-writer",
        )
        adoption_context = replace(
            fixture.context, migration_evidence=evidence
        )
        adoption = registrar.prepare(
            registrar.preview(
                fixture.config_path, remote, context=adoption_context
            )
        )
        registrar.apply(adoption, fixture_approval(adoption))

        local = _stdio("b" * 40)
        local_context = replace(
            fixture.context,
            source_revision=local.source_revision,
            definition_digest=local.digest,
            migration_evidence=None,
            auth_binding=AuthBinding.none(
                binding_id="preserve-user-empty-headers",
                host=fixture.context.host,
                surface=fixture.context.surface,
                scope=fixture.context.scope,
                target_origin_digest=local.target_origin_digest,
            ),
        )
        switch = registrar.prepare(
            registrar.preview(
                fixture.config_path, local, context=local_context
            )
        )
        registrar.apply(switch, fixture_approval(switch))
        entry = json.loads(fixture.config_path.read_text())["mcpServers"][
            local.native_name
        ]
        assert entry["headers"] == {}
        assert registrar.preview_unregister(
            fixture.config_path, context=local_context
        ).conflicts == (ReasonCode.REMOVAL_CONFLICT,)
